"""
tests/test_business_plan_service.py

NRM-001: services/business_plan_service.py 테스트.
실제 LLM(ai/) 대신 정해진 값을 돌려주는 가짜 normalize_fn을 주입해서 검증한다.
"""

import pytest

from app.models.business_plan import BusinessPlan
from app.models.company import CompanyProfile
from app.repositories.business_plan_repository import BusinessPlanNotFoundError
from app.schemas.business_plan import (
    FundingInfo,
    NormalizedBusinessPlanSchema,
    ProblemInfo,
    SolutionInfo,
    TeamInfo,
)
from app.services.business_plan_service import (
    NoSourceTextError,
    normalize_business_plan,
    validate_normalized,
)

pytestmark = pytest.mark.anyio


def _complete_normalized() -> NormalizedBusinessPlanSchema:
    return NormalizedBusinessPlanSchema(
        problem=ProblemInfo(background="배경"),
        solution=SolutionInfo(summary="요약"),
        funding=FundingInfo(scale_up_strategy="전략"),
        team=TeamInfo(capabilities="역량"),
    )


async def _create_business_plan(
    db_session, company_profile: CompanyProfile, **overrides
) -> BusinessPlan:
    defaults = dict(company_profile_id=company_profile.id, title="테스트 사업계획서")
    defaults.update(overrides)
    plan = BusinessPlan(**defaults)
    db_session.add(plan)
    await db_session.flush()
    return plan


def test_validate_normalized_reports_no_missing_fields_when_complete():
    result = validate_normalized(_complete_normalized())

    assert result.is_valid is True
    assert result.missing_required_fields == []


def test_validate_normalized_lists_missing_dotted_paths():
    normalized = NormalizedBusinessPlanSchema(
        solution=SolutionInfo(summary="요약"),
    )

    result = validate_normalized(normalized)

    assert result.is_valid is False
    assert result.missing_required_fields == [
        "problem.background",
        "funding.scale_up_strategy",
        "team.capabilities",
    ]


async def test_normalize_business_plan_prefers_extracted_text_over_db(
    db_session, test_company_profile
):
    plan = await _create_business_plan(
        db_session, test_company_profile, raw_text="DB 원문"
    )
    seen_texts: list[str] = []

    async def fake_normalize(text: str) -> NormalizedBusinessPlanSchema:
        seen_texts.append(text)
        return _complete_normalized()

    outcome = await normalize_business_plan(
        db_session,
        business_plan_id=plan.id,
        normalize_fn=fake_normalize,
        extracted_text="테스트 전용 원문",
    )

    assert seen_texts == ["테스트 전용 원문"]
    assert outcome.validation_result.is_valid is True
    assert outcome.normalized == _complete_normalized()


async def test_normalize_business_plan_falls_back_to_db_raw_text(
    db_session, test_company_profile
):
    plan = await _create_business_plan(
        db_session, test_company_profile, raw_text="DB 원문"
    )
    seen_texts: list[str] = []

    async def fake_normalize(text: str) -> NormalizedBusinessPlanSchema:
        seen_texts.append(text)
        return _complete_normalized()

    await normalize_business_plan(
        db_session, business_plan_id=plan.id, normalize_fn=fake_normalize
    )

    assert seen_texts == ["DB 원문"]


async def test_normalize_business_plan_persists_result(
    db_session, test_company_profile
):
    plan = await _create_business_plan(
        db_session, test_company_profile, raw_text="DB 원문"
    )

    async def fake_normalize(text: str) -> NormalizedBusinessPlanSchema:
        return _complete_normalized()

    outcome = await normalize_business_plan(
        db_session, business_plan_id=plan.id, normalize_fn=fake_normalize
    )

    await db_session.refresh(plan)
    assert plan.analysis_json == _complete_normalized().model_dump()
    assert plan.analyzed_at == outcome.analyzed_at


async def test_normalize_business_plan_raises_when_no_text_available(
    db_session, test_company_profile
):
    plan = await _create_business_plan(db_session, test_company_profile, raw_text=None)

    async def fake_normalize(text: str) -> NormalizedBusinessPlanSchema:
        raise AssertionError("텍스트가 없으면 normalize_fn이 호출되면 안 됨")

    with pytest.raises(NoSourceTextError):
        await normalize_business_plan(
            db_session, business_plan_id=plan.id, normalize_fn=fake_normalize
        )


async def test_normalize_business_plan_raises_when_plan_missing(db_session):
    async def fake_normalize(text: str) -> NormalizedBusinessPlanSchema:
        raise AssertionError("business_plan이 없으면 normalize_fn이 호출되면 안 됨")

    with pytest.raises(BusinessPlanNotFoundError):
        await normalize_business_plan(
            db_session, business_plan_id=999_999, normalize_fn=fake_normalize
        )

"""
tests/test_business_plan_analysis.py

services.business_plan_analysis_service.run_analysis 테스트.
OCR(extract_fn)·정규화(normalize_fn)는 외부 호출이라 가짜 함수로 주입한다.
"""

import pytest

from app.models.business_plan import BusinessPlan
from app.models.company import CompanyProfile
from app.repositories.business_plan_repository import (
    BusinessPlanNotFoundError,
    get_by_id,
)
from app.ai.normalizer import AiNormalizationError
from app.schemas.business_plan import (
    NormalizedBusinessPlanSchema,
    ProblemInfo,
)
from app.services.business_plan_analysis_service import (
    NoUploadedFileError,
    run_analysis,
)

pytestmark = pytest.mark.anyio


async def _create_plan(
    db_session, profile: CompanyProfile, **overrides
) -> BusinessPlan:
    defaults = dict(
        company_profile_id=profile.id,
        title="테스트 사업계획서",
        file_url="storage/uploads/test.pdf",
        file_type="PDF",
    )
    defaults.update(overrides)
    plan = BusinessPlan(**defaults)
    db_session.add(plan)
    await db_session.flush()
    return plan


def _fake_extract(text: str, file_type: str = "PDF"):
    async def _extract(path: str) -> tuple[str, str]:
        return text, file_type

    return _extract


def _fake_normalize(result: NormalizedBusinessPlanSchema):
    async def _normalize(text: str) -> NormalizedBusinessPlanSchema:
        return result

    return _normalize


async def test_run_analysis_saves_raw_text_and_analysis_json(
    db_session, test_company_profile
):
    plan = await _create_plan(db_session, test_company_profile)
    normalized = NormalizedBusinessPlanSchema(problem=ProblemInfo(background="배경"))

    outcome = await run_analysis(
        db_session,
        plan.id,
        extract_fn=_fake_extract("OCR로 뽑은 원문"),
        normalize_fn=_fake_normalize(normalized),
    )

    assert outcome.normalized == normalized

    fetched = await get_by_id(db_session, plan.id)
    assert fetched.raw_text == "OCR로 뽑은 원문"
    assert fetched.analysis_json == normalized.model_dump()
    assert fetched.analyzed_at is not None


async def test_run_analysis_preserves_ocr_result_when_normalize_fails(
    db_session, test_company_profile
):
    """정규화가 실패해도, 먼저 커밋한 OCR 결과(raw_text)는 남아야 한다."""
    plan = await _create_plan(db_session, test_company_profile)

    async def failing_normalize(text: str) -> NormalizedBusinessPlanSchema:
        raise AiNormalizationError("LLM 실패")

    with pytest.raises(AiNormalizationError):
        await run_analysis(
            db_session,
            plan.id,
            extract_fn=_fake_extract("보존돼야 할 원문"),
            normalize_fn=failing_normalize,
        )

    # save_raw_text는 Core UPDATE라 ORM 캐시를 갱신하지 않으므로, 커밋된 DB 값을
    # 다시 읽어 확인한다(운영에선 폴링이 새 세션으로 조회하므로 자연히 최신값).
    await db_session.refresh(plan)
    assert plan.raw_text == "보존돼야 할 원문"  # OCR 결과는 커밋되어 남음
    assert plan.analysis_json is None  # 정규화는 실패했으므로 비어 있음


async def test_run_analysis_raises_when_plan_missing(db_session):
    with pytest.raises(BusinessPlanNotFoundError):
        await run_analysis(
            db_session,
            999_999,
            extract_fn=_fake_extract("x"),
            normalize_fn=_fake_normalize(NormalizedBusinessPlanSchema()),
        )


async def test_run_analysis_raises_when_no_uploaded_file(
    db_session, test_company_profile
):
    plan = await _create_plan(db_session, test_company_profile, file_url=None)

    with pytest.raises(NoUploadedFileError):
        await run_analysis(
            db_session,
            plan.id,
            extract_fn=_fake_extract("x"),
            normalize_fn=_fake_normalize(NormalizedBusinessPlanSchema()),
        )

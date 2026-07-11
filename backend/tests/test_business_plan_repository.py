"""
tests/test_business_plan_repository.py

NRM-001: repositories/business_plan_repository.py 테스트.
모든 테스트는 conftest.db_session이 열어 둔 외부 트랜잭션 안에서 실행되고
테스트가 끝나면 롤백되므로 실제 DB에는 데이터가 남지 않는다.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.business_plan import BusinessPlan
from app.models.company import CompanyProfile
from app.models.user import User
from app.repositories.business_plan_repository import (
    BusinessPlanNotFoundError,
    finish_analysis,
    get_by_id,
    get_owned_by_user,
    get_raw_text,
    list_recent,
    save_normalization_result,
    set_analysis_step,
    try_claim_analysis,
)
from app.schemas.business_plan import JobStatus

pytestmark = pytest.mark.anyio


async def _create_business_plan(
    db_session, company_profile: CompanyProfile, **overrides
) -> BusinessPlan:
    defaults = dict(company_profile_id=company_profile.id, title="테스트 사업계획서")
    defaults.update(overrides)
    plan = BusinessPlan(**defaults)
    db_session.add(plan)
    await db_session.flush()
    return plan


async def test_get_raw_text_returns_text_when_present(db_session, test_company_profile):
    plan = await _create_business_plan(
        db_session, test_company_profile, raw_text="원문 내용입니다."
    )

    result = await get_raw_text(db_session, plan.id)

    assert result == "원문 내용입니다."


async def test_get_raw_text_returns_none_when_raw_text_empty(
    db_session, test_company_profile
):
    plan = await _create_business_plan(db_session, test_company_profile, raw_text=None)

    result = await get_raw_text(db_session, plan.id)

    assert result is None


async def test_get_raw_text_raises_when_plan_missing(db_session):
    with pytest.raises(BusinessPlanNotFoundError):
        await get_raw_text(db_session, business_plan_id=999_999)


async def test_save_normalization_result_updates_analysis_fields(
    db_session, test_company_profile
):
    plan = await _create_business_plan(db_session, test_company_profile)
    normalized_json = {"schema_version": "1.0", "company": {"name": "테스트기업"}}
    analyzed_at = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)

    updated = await save_normalization_result(
        db_session,
        business_plan_id=plan.id,
        normalized_json=normalized_json,
        analyzed_at=analyzed_at,
    )

    assert updated.analysis_json == normalized_json
    assert updated.analyzed_at == analyzed_at.replace(tzinfo=None)

    reloaded = await get_by_id(db_session, plan.id)
    assert reloaded.analysis_json == normalized_json


async def test_save_normalization_result_raises_when_plan_missing(db_session):
    with pytest.raises(BusinessPlanNotFoundError):
        await save_normalization_result(
            db_session, business_plan_id=999_999, normalized_json={}
        )


async def test_get_owned_by_user_returns_plan_for_owner(
    db_session, test_user, test_company_profile
):
    plan = await _create_business_plan(db_session, test_company_profile)

    result = await get_owned_by_user(db_session, plan.id, test_user.id)

    assert result is not None
    assert result.id == plan.id


async def test_get_owned_by_user_returns_none_for_other_user(
    db_session, test_company_profile
):
    """다른 유저 소유의 계획서는 존재해도 None(호출부에서 404 처리)."""
    plan = await _create_business_plan(db_session, test_company_profile)

    other_user = User(kakao_id="other-kakao-id")
    db_session.add(other_user)
    await db_session.flush()

    result = await get_owned_by_user(db_session, plan.id, other_user.id)

    assert result is None


async def test_get_owned_by_user_returns_none_when_plan_missing(db_session, test_user):
    result = await get_owned_by_user(db_session, 999_999, test_user.id)

    assert result is None


# ---------------------------------------------------------------------------
# 분석 잡 상태 (try_claim_analysis / set_analysis_step / finish_analysis)
# ---------------------------------------------------------------------------


def _stale_before(minutes: int = 10) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes)


async def test_try_claim_analysis_claims_when_never_started(
    db_session, test_company_profile
):
    plan = await _create_business_plan(db_session, test_company_profile)

    claimed = await try_claim_analysis(
        db_session, plan.id, stale_before=_stale_before()
    )

    assert claimed is True
    await db_session.refresh(plan)
    assert plan.analysis_status == JobStatus.PROCESSING.value
    assert plan.analysis_started_at is not None
    assert plan.analysis_step is None
    assert plan.analysis_error is None


async def test_try_claim_analysis_rejects_while_processing(
    db_session, test_company_profile
):
    """진행 중(processing) 잡은 재선점 불가 — 중복 분석 방지의 핵심."""
    plan = await _create_business_plan(db_session, test_company_profile)

    first = await try_claim_analysis(db_session, plan.id, stale_before=_stale_before())
    second = await try_claim_analysis(db_session, plan.id, stale_before=_stale_before())

    assert first is True
    assert second is False


async def test_try_claim_analysis_reclaims_stale_processing(
    db_session, test_company_profile
):
    """서버가 죽어 processing으로 박제된 잡은 stale 기준을 넘기면 재선점 가능."""
    plan = await _create_business_plan(
        db_session,
        test_company_profile,
        analysis_status=JobStatus.PROCESSING.value,
        analysis_started_at=datetime.now(timezone.utc).replace(tzinfo=None)
        - timedelta(minutes=30),
    )

    claimed = await try_claim_analysis(
        db_session, plan.id, stale_before=_stale_before(minutes=10)
    )

    assert claimed is True


async def test_try_claim_analysis_reclaims_after_failure(
    db_session, test_company_profile
):
    """failed 상태는 재시도(재선점)를 허용하고 이전 실패 사유를 지운다."""
    plan = await _create_business_plan(
        db_session,
        test_company_profile,
        analysis_status=JobStatus.FAILED.value,
        analysis_error="이전 실패",
    )

    claimed = await try_claim_analysis(
        db_session, plan.id, stale_before=_stale_before()
    )

    assert claimed is True
    await db_session.refresh(plan)
    assert plan.analysis_status == JobStatus.PROCESSING.value
    assert plan.analysis_error is None


async def test_try_claim_analysis_returns_false_when_plan_missing(db_session):
    claimed = await try_claim_analysis(
        db_session, 999_999, stale_before=_stale_before()
    )

    assert claimed is False


async def test_set_analysis_step_and_finish_analysis_update_row(
    db_session, test_company_profile
):
    plan = await _create_business_plan(db_session, test_company_profile)
    await try_claim_analysis(db_session, plan.id, stale_before=_stale_before())

    await set_analysis_step(db_session, plan.id, "normalizing")
    await db_session.refresh(plan)
    assert plan.analysis_step == "normalizing"

    await finish_analysis(
        db_session, plan.id, status=JobStatus.FAILED.value, error_message="LLM 실패"
    )
    await db_session.refresh(plan)
    assert plan.analysis_status == JobStatus.FAILED.value
    assert plan.analysis_step is None  # 종료 시 단계 표시는 비운다
    assert plan.analysis_error == "LLM 실패"


async def test_list_recent_orders_by_created_at_desc_and_respects_limit(
    db_session, test_company_profile
):
    older = await _create_business_plan(
        db_session,
        test_company_profile,
        title="older",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None),
    )
    newer = await _create_business_plan(
        db_session,
        test_company_profile,
        title="newer",
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc).replace(tzinfo=None),
    )

    result = await list_recent(db_session, limit=1)

    assert len(result) == 1
    assert result[0].id == newer.id
    assert result[0].id != older.id

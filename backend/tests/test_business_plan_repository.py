"""
tests/test_business_plan_repository.py

NRM-001: repositories/business_plan_repository.py 테스트.
모든 테스트는 conftest.db_session이 열어 둔 외부 트랜잭션 안에서 실행되고
테스트가 끝나면 롤백되므로 실제 DB에는 데이터가 남지 않는다.
"""

from datetime import datetime, timezone

import pytest

from app.models.business_plan import BusinessPlan
from app.models.company import CompanyProfile
from app.repositories.business_plan_repository import (
    BusinessPlanNotFoundError,
    get_by_id,
    get_raw_text,
    list_recent,
    save_normalization_result,
)

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

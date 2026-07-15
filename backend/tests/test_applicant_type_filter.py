"""tests/test_applicant_type_filter.py

신청주체(기업 vs 비기업) 필터 검증. 순수 판정 헬퍼는 DB 없이,
notice_id 반환 메서드는 conftest.db_session(SAVEPOINT 롤백) 위에서 검증한다.
"""

import pytest

from app.repositories.notice_repository import (
    get_or_create_source,
    replace_notice_target_type,
    upsert_notice,
)
from app.services.applicant_type_filter import (
    filter_notice_ids_by_applicant_type,
    passes_applicant_type_filter,
)

pytestmark = pytest.mark.anyio


# --- 순수 판정 헬퍼 (DB 불필요) ---


def test_registered_business_cuts_non_company_only_notice():
    # 개인/법인사업자는 비기업 전용(일반인/대학생) 공고를 컷한다.
    assert passes_applicant_type_filter(["일반인", "대학생"], "개인사업자") is False
    assert passes_applicant_type_filter(["연구기관"], "법인사업자") is False


def test_company_tag_present_passes():
    # 비기업 태그가 섞여 있어도 기업성 태그가 하나라도 있으면 통과.
    assert passes_applicant_type_filter(["대학생", "일반기업"], "개인사업자") is True
    assert passes_applicant_type_filter(["중소기업"], "법인사업자") is True


def test_empty_target_types_pass():
    # 신청대상 정보가 없으면(미상) 안전하게 통과.
    assert passes_applicant_type_filter([], "법인사업자") is True


def test_pre_founder_and_unknown_are_not_cut():
    # 예비창업자·미입력은 비기업 전용 공고라도 컷하지 않는다.
    assert passes_applicant_type_filter(["일반인"], "예비창업자") is True
    assert passes_applicant_type_filter(["대학생"], None) is True


# --- notice_id 반환 메서드 (DB) ---


async def _create_notice(db_session, source, external_id, target_types):
    notice_id = await upsert_notice(
        db_session,
        source_id=source.id,
        external_id=external_id,
        title=f"공고 {external_id}",
        application_start_date=None,
        application_end_date=None,
        status="모집중",
        is_actionable=True,
        source_url=None,
        apply_url=None,
        summary_text=None,
    )
    await replace_notice_target_type(db_session, notice_id, target_types)
    return notice_id


async def test_filter_returns_surviving_ids_in_order(db_session):
    source = await get_or_create_source(
        db_session, "applicant-type-test-source", "https://example.com", "API"
    )

    non_company = await _create_notice(db_session, source, "a", ["일반인", "대학생"])
    company = await _create_notice(db_session, source, "b", ["중소기업"])
    mixed = await _create_notice(db_session, source, "c", ["대학생", "일반기업"])
    unknown = await _create_notice(db_session, source, "d", [])
    ordered = [non_company, company, mixed, unknown]

    # 법인사업자: 비기업 전용(a)만 빠지고 입력 순서 유지.
    kept = await filter_notice_ids_by_applicant_type(db_session, ordered, "법인사업자")
    assert kept == [company, mixed, unknown]

    # 예비창업자: 컷 없이 전부 통과.
    kept_pre = await filter_notice_ids_by_applicant_type(
        db_session, ordered, "예비창업자"
    )
    assert kept_pre == ordered


async def test_filter_empty_input_returns_empty(db_session):
    assert await filter_notice_ids_by_applicant_type(db_session, [], "개인사업자") == []

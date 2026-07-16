"""1차 필터링(하드필터) 서비스 검증.

축별 판정/집계는 순수 함수(_passes_all_axes 등)로 DB 없이 검증하고,
end-to-end 배선(프로필 → 통과 id/counts)은 conftest.db_session 위에서
검증한다. 축별 정확한 집계는 순수 테스트가 담당하고, 통합 테스트는 다른
공고가 로컬 DB에 섞여 있어도 깨지지 않게 내가 만든 공고의 통과/탈락과
counts 합의 일관성만 본다.
"""

from datetime import date

import pytest

from app.repositories.notice_eligibility_repository import NoticeEligibilityRow
from app.repositories.notice_repository import (
    get_or_create_source,
    replace_notice_region,
    replace_notice_target_type,
    upsert_notice,
)
from app.services.notice_eligibility_service import (
    _derive_business_years,
    _derive_is_prestartup,
    _full_years,
    _passes_all_axes,
    get_eligible_notices,
    passes_period,
    passes_region,
)

pytestmark = pytest.mark.anyio

_TODAY = date(2026, 7, 15)


# --- 지역 축 ---


def test_region_permissive_when_company_or_notice_missing():
    assert passes_region(frozenset({"11"}), None)  # 기업 지역 없음 → 필터 불가
    assert passes_region(frozenset(), "11")  # 공고 지역 제한 없음


def test_region_all_and_match_and_mismatch():
    assert passes_region(frozenset({"ALL"}), "11")
    assert passes_region(frozenset({"11", "26"}), "11")
    assert not passes_region(frozenset({"26"}), "11")


# --- 기간 축 ---


def test_period_recruiting_status_always_passes():
    assert passes_period("모집중", None, None, _TODAY)


def test_period_by_dates():
    assert passes_period("확인필요", date(2026, 7, 1), date(2026, 7, 31), _TODAY)
    assert passes_period("확인필요", date(2026, 7, 1), None, _TODAY)  # 종료일 없음
    assert not passes_period("확인필요", date(2026, 8, 1), None, _TODAY)  # 시작 전
    assert not passes_period(
        "확인필요", date(2026, 7, 1), date(2026, 7, 10), _TODAY
    )  # 종료 후
    assert not passes_period("마감", None, None, _TODAY)  # 시작일 없음 + 마감


# --- 축별 탈락 귀속 (순수) ---


def _row(**kwargs) -> NoticeEligibilityRow:
    base = dict(
        notice_id=1,
        status="모집중",
        application_start_date=None,
        application_end_date=None,
        target_business_years_max=None,
        target_allows_prestartup=None,
        region_codes=frozenset({"ALL"}),
        target_types=(),
    )
    base.update(kwargs)
    return NoticeEligibilityRow(**base)


_FOUNDED_COMPANY = dict(
    region_code="11",
    business_type="법인사업자",
    is_prestartup=False,
    business_years=2,
    today=_TODAY,
)


def test_axis_pass():
    assert _passes_all_axes(_row(), **_FOUNDED_COMPANY) is None


def test_axis_region_rejected_first():
    row = _row(region_codes=frozenset({"26"}))
    assert _passes_all_axes(row, **_FOUNDED_COMPANY) == "지역_탈락"


def test_axis_target_rejected():
    row = _row(target_types=("대학생", "연구기관"))
    assert _passes_all_axes(row, **_FOUNDED_COMPANY) == "대상_탈락"


def test_axis_business_years_rejected():
    # max_years=2, 업력 2 → 2<2 거짓 → 탈락.
    row = _row(target_business_years_max=2, target_allows_prestartup=False)
    assert _passes_all_axes(row, **_FOUNDED_COMPANY) == "업력_탈락"


def test_axis_period_rejected():
    row = _row(status="마감")
    assert _passes_all_axes(row, **_FOUNDED_COMPANY) == "기간_탈락"


def test_axis_order_region_before_period():
    # 지역·기간 둘 다 탈락 조건이면 먼저 오는 지역으로 귀속.
    row = _row(region_codes=frozenset({"26"}), status="마감")
    assert _passes_all_axes(row, **_FOUNDED_COMPANY) == "지역_탈락"


# --- 기업측 값 도출 ---


def test_full_years_floor_before_birthday():
    assert _full_years(date(2024, 8, 1), _TODAY) == 1  # 생일 안 지남
    assert _full_years(date(2024, 7, 1), _TODAY) == 2  # 생일 지남


def test_derive_is_prestartup():
    assert _derive_is_prestartup("예비창업자", None, None)
    assert _derive_is_prestartup(None, "예비창업자", None)
    assert _derive_is_prestartup(None, None, "예비창업자")  # 분석값 폴백
    assert not _derive_is_prestartup("법인사업자", "초기창업", None)


def test_derive_business_years_precedence():
    # 프로필 업력 우선.
    assert _derive_business_years(3, date(2000, 1, 1), 1990, _TODAY) == 3
    # 없으면 설립일.
    assert _derive_business_years(None, date(2024, 7, 1), 1990, _TODAY) == 2
    # 그것도 없으면 분석값 founded_year.
    assert _derive_business_years(None, None, 2020, _TODAY) == 6
    # 전부 없으면 None.
    assert _derive_business_years(None, None, None, _TODAY) is None


# --- end-to-end (DB) ---


async def _make_notice(
    db_session,
    source,
    external_id,
    *,
    status="모집중",
    start=None,
    end=None,
    years_max=None,
    allows_prestartup=None,
    regions=(("ALL", "전국"),),
    target_types=(),
):
    notice_id = await upsert_notice(
        db_session,
        source_id=source.id,
        external_id=external_id,
        title=f"공고 {external_id}",
        application_start_date=start,
        application_end_date=end,
        status=status,
        is_actionable=status == "모집중",
        source_url=None,
        apply_url=None,
        summary_text=None,
        target_business_years_max=years_max,
        target_allows_prestartup=allows_prestartup,
    )
    await replace_notice_region(db_session, notice_id, list(regions))
    await replace_notice_target_type(db_session, notice_id, list(target_types))
    return notice_id


async def test_get_eligible_notices_end_to_end(db_session, test_company_profile):
    profile = test_company_profile
    profile.region_code = "11"
    profile.business_type = "법인사업자"
    profile.company_stage = "초기창업"
    profile.business_years = 2
    await db_session.flush()

    source = await get_or_create_source(
        db_session, "eligibility-test-source", "https://example.com", "API"
    )

    passes_all = await _make_notice(
        db_session,
        source,
        "pass1",
        years_max=7,
        allows_prestartup=False,
        target_types=["중소기업"],
    )
    passes_region_specific = await _make_notice(
        db_session,
        source,
        "pass2",
        regions=[("11", "서울")],
    )
    region_fail = await _make_notice(
        db_session,
        source,
        "regf",
        regions=[("26", "부산")],
    )
    target_fail = await _make_notice(
        db_session,
        source,
        "tgtf",
        target_types=["대학생", "연구기관"],
    )
    years_fail = await _make_notice(
        db_session,
        source,
        "yrf",
        years_max=2,
        allows_prestartup=False,
    )
    period_fail = await _make_notice(db_session, source, "perf", status="마감")

    result = await get_eligible_notices(db_session, profile, today=_TODAY)

    ids = set(result.notice_ids)
    assert {passes_all, passes_region_specific} <= ids
    assert ids.isdisjoint({region_fail, target_fail, years_fail, period_fail})

    counts = result.counts
    assert counts["통과"] == len(result.notice_ids)
    axis_sum = (
        counts["지역_탈락"]
        + counts["대상_탈락"]
        + counts["업력_탈락"]
        + counts["기간_탈락"]
        + counts["통과"]
    )
    assert axis_sum == counts["input"]


async def test_get_eligible_notices_missing_profile_region_is_permissive(
    db_session, test_company_profile
):
    # 프로필 지역이 없으면 지역 축으로는 아무도 탈락하지 않는다.
    profile = test_company_profile
    profile.business_type = "법인사업자"
    await db_session.flush()

    source = await get_or_create_source(
        db_session, "eligibility-test-source", "https://example.com", "API"
    )

    only_busan = await _make_notice(
        db_session,
        source,
        "busan",
        regions=[("26", "부산")],
        target_types=["중소기업"],
    )
    result = await get_eligible_notices(db_session, profile, today=_TODAY)
    assert only_busan in set(result.notice_ids)

"""
tests/test_notice_collection_service.py

services/notice_collection_service.py 테스트.
순수 파싱/필터링 함수는 DB 없이, backfill_notice_categories는
conftest.db_session(SAVEPOINT 롤백) 위에서 검증한다.
"""

import json
from datetime import date

import pytest

from app.models.notice import Notice
from app.models.notice_source import NoticeSource
from app.models.raw import BizinfoRaw, KstartupRaw
from app.repositories.notice_repository import upsert_notice
from app.services.notice_collection_service import (
    _bizinfo_raw_category_key,
    _derive_status_from_dates,
    _is_bizinfo_fund_category,
    _is_kstartup_fund_category,
    _is_rolling_open,
    _kstartup_raw_category_key,
    _parse_bizinfo_attachments,
    _parse_bizinfo_date_range,
    _parse_bizinfo_regions,
    _parse_kstartup_date,
    _parse_regions,
    _within_collection_window,
    backfill_notice_categories,
)

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# 카테고리 키 매핑
# ---------------------------------------------------------------------------


def test_bizinfo_raw_category_key_uses_대분류_for_non_경영():
    assert _bizinfo_raw_category_key({"pldirSportRealmLclasCodeNm": "금융"}) == (
        "BIZINFO:금융"
    )


def test_bizinfo_raw_category_key_appends_중분류_for_경영():
    item = {
        "pldirSportRealmLclasCodeNm": "경영",
        "pldirSportRealmMlsfcCodeNm": "판로",
    }
    assert _bizinfo_raw_category_key(item) == "BIZINFO:경영:판로"


def test_bizinfo_raw_category_key_none_when_경영_missing_중분류():
    item = {"pldirSportRealmLclasCodeNm": "경영"}
    assert _bizinfo_raw_category_key(item) is None


def test_bizinfo_raw_category_key_none_when_lclas_missing():
    assert _bizinfo_raw_category_key({}) is None


def test_kstartup_raw_category_key_present():
    assert _kstartup_raw_category_key({"supt_biz_clsfc": "정책자금"}) == (
        "KSTARTUP:정책자금"
    )


def test_kstartup_raw_category_key_none_when_missing():
    assert _kstartup_raw_category_key({}) is None


# ---------------------------------------------------------------------------
# 자금 카테고리 필터 (수집 시 자금만 저장)
# ---------------------------------------------------------------------------


def test_is_bizinfo_fund_category_only_matches_금융():
    assert _is_bizinfo_fund_category({"pldirSportRealmLclasCodeNm": "금융"}) is True
    assert _is_bizinfo_fund_category({"pldirSportRealmLclasCodeNm": "기술"}) is False


@pytest.mark.parametrize("clsfc", ["정책자금", "융자ㆍ보증", "사업화"])
def test_is_kstartup_fund_category_matches_known_values(clsfc):
    assert _is_kstartup_fund_category({"supt_biz_clsfc": clsfc}) is True


def test_is_kstartup_fund_category_false_for_other_values():
    assert _is_kstartup_fund_category({"supt_biz_clsfc": "R&D"}) is False


# ---------------------------------------------------------------------------
# 날짜/기간 파싱
# ---------------------------------------------------------------------------


def test_parse_bizinfo_date_range_parses_valid_range():
    start, end = _parse_bizinfo_date_range("2026-07-27 ~ 2026-07-30")
    assert start == date(2026, 7, 27)
    assert end == date(2026, 7, 30)


def test_parse_bizinfo_date_range_none_when_no_tilde():
    assert _parse_bizinfo_date_range("상시") == (None, None)


def test_parse_bizinfo_date_range_none_when_unparsable():
    assert _parse_bizinfo_date_range("2026년 7월 ~ 8월") == (None, None)


def test_parse_kstartup_date_parses_yyyymmdd():
    assert _parse_kstartup_date("20260727") == date(2026, 7, 27)


def test_parse_kstartup_date_none_when_invalid():
    assert _parse_kstartup_date("2026-07-27") is None
    assert _parse_kstartup_date(None) is None


def test_is_rolling_open_matches_known_keywords():
    assert _is_rolling_open("예산 소진 시까지") is True
    assert _is_rolling_open("2026-07-27 ~ 2026-07-30") is False
    assert _is_rolling_open(None) is False


def test_within_collection_window_true_when_start_date_missing():
    assert _within_collection_window(None) is True


def test_within_collection_window_false_for_old_notice():
    assert _within_collection_window(date(2020, 1, 1)) is False


# ---------------------------------------------------------------------------
# 지역 파싱
# ---------------------------------------------------------------------------


def test_parse_regions_maps_known_names_and_dedupes_by_code():
    regions = _parse_regions("서울,경기도,서울특별시")
    assert regions == [("11", "서울"), ("41", "경기도")]


def test_parse_regions_skips_unknown_region_name():
    assert _parse_regions("아틀란티스") == []


def test_parse_bizinfo_regions_picks_only_region_tags_from_mixed_hashtags():
    regions = _parse_bizinfo_regions("경영,서울,부산,2026,지식재산처")
    assert regions == [("11", "서울"), ("26", "부산")]


# ---------------------------------------------------------------------------
# 기업마당 첨부파일 파싱 ("@"로 이어붙은 다건 응답)
# ---------------------------------------------------------------------------


def test_parse_bizinfo_attachments_splits_at_sign_joined_multi_file():
    item = {
        "fileNm": "a.pdf@b.hwp",
        "flpthNm": "https://example.com/a@https://example.com/b",
    }
    assert _parse_bizinfo_attachments(item) == [
        ("a.pdf", "https://example.com/a"),
        ("b.hwp", "https://example.com/b"),
    ]


def test_parse_bizinfo_attachments_skips_mismatched_counts():
    item = {"fileNm": "a.pdf@b.hwp", "flpthNm": "https://example.com/a"}
    assert _parse_bizinfo_attachments(item) == []


def test_parse_bizinfo_attachments_dedupes_by_url_across_fields():
    item = {
        "fileNm": "a.pdf",
        "flpthNm": "https://example.com/a",
        "printFileNm": "a-print.pdf",
        "printFlpthNm": "https://example.com/a",
    }
    assert _parse_bizinfo_attachments(item) == [("a.pdf", "https://example.com/a")]


# ---------------------------------------------------------------------------
# 모집 상태 판별
# ---------------------------------------------------------------------------


def test_derive_status_예정_when_start_date_in_future():
    status, is_actionable = _derive_status_from_dates(date(2099, 1, 1), None)
    assert (status, is_actionable) == ("예정", False)


def test_derive_status_마감_when_end_date_passed():
    status, is_actionable = _derive_status_from_dates(None, date(2020, 1, 1))
    assert (status, is_actionable) == ("마감", False)


def test_derive_status_모집중_when_both_dates_bracket_today():
    status, is_actionable = _derive_status_from_dates(
        date(2020, 1, 1), date(2099, 1, 1)
    )
    assert (status, is_actionable) == ("모집중", True)


def test_derive_status_모집중_when_rolling_open_keyword():
    status, is_actionable = _derive_status_from_dates(
        None, None, raw_period="예산 소진 시까지"
    )
    assert (status, is_actionable) == ("모집중", True)


def test_derive_status_확인필요_when_no_signal():
    status, is_actionable = _derive_status_from_dates(None, None, raw_period=None)
    assert (status, is_actionable) == ("확인필요", False)


# ---------------------------------------------------------------------------
# backfill_notice_categories (DB 기반)
# ---------------------------------------------------------------------------


async def _create_source(db_session, name: str) -> NoticeSource:
    source = NoticeSource(source_name=name, base_url="https://example.com")
    db_session.add(source)
    await db_session.flush()
    return source


async def test_backfill_fills_category_id_from_stored_bizinfo_raw(db_session):
    source = await _create_source(db_session, "기업마당-백필테스트")
    notice_id = await upsert_notice(
        db_session,
        source_id=source.id,
        external_id="biz-1",
        title="테스트 공고",
        application_start_date=None,
        application_end_date=None,
        status="모집중",
        is_actionable=True,
        source_url=None,
        apply_url=None,
        summary_text=None,
    )
    db_session.add(
        BizinfoRaw(
            key="biz-1",
            field=json.dumps({"pldirSportRealmLclasCodeNm": "금융"}),
            notice_id=notice_id,
        )
    )
    await db_session.flush()

    result = await backfill_notice_categories(db_session)

    from app.models.notice import Notice

    notice = await db_session.get(Notice, notice_id)
    assert result["updated"] >= 1
    assert notice.category_id == 1  # kg_category 시드 데이터 기준 "자금"


async def test_backfill_leaves_category_id_null_when_raw_category_unmapped(db_session):
    source = await _create_source(db_session, "기업마당-백필테스트2")
    notice_id = await upsert_notice(
        db_session,
        source_id=source.id,
        external_id="biz-2",
        title="테스트 공고2",
        application_start_date=None,
        application_end_date=None,
        status="모집중",
        is_actionable=True,
        source_url=None,
        apply_url=None,
        summary_text=None,
    )
    db_session.add(
        BizinfoRaw(
            key="biz-2",
            field=json.dumps({"pldirSportRealmLclasCodeNm": "존재하지않는분류"}),
            notice_id=notice_id,
        )
    )
    await db_session.flush()

    await backfill_notice_categories(db_session)

    notice = await db_session.get(Notice, notice_id)
    assert notice.category_id is None


async def test_backfill_skips_malformed_raw_json_without_aborting_batch(db_session):
    """raw_field가 깨져 있어도 그 건만 건너뛰고 나머지는 계속 처리한다."""
    source = await _create_source(db_session, "K-Startup-백필테스트")
    broken_notice_id = await upsert_notice(
        db_session,
        source_id=source.id,
        external_id="ks-broken",
        title="깨진 원본",
        application_start_date=None,
        application_end_date=None,
        status="모집중",
        is_actionable=True,
        source_url=None,
        apply_url=None,
        summary_text=None,
    )
    ok_notice_id = await upsert_notice(
        db_session,
        source_id=source.id,
        external_id="ks-ok",
        title="정상 원본",
        application_start_date=None,
        application_end_date=None,
        status="모집중",
        is_actionable=True,
        source_url=None,
        apply_url=None,
        summary_text=None,
    )
    db_session.add(
        KstartupRaw(
            key="ks-broken", field="이건 JSON이 아님", notice_id=broken_notice_id
        )
    )
    db_session.add(
        KstartupRaw(
            key="ks-ok",
            field=json.dumps({"supt_biz_clsfc": "정책자금"}),
            notice_id=ok_notice_id,
        )
    )
    await db_session.flush()

    result = await backfill_notice_categories(db_session)

    broken = await db_session.get(Notice, broken_notice_id)
    ok = await db_session.get(Notice, ok_notice_id)
    assert broken.category_id is None
    assert ok.category_id is not None
    assert result["checked"] >= 2

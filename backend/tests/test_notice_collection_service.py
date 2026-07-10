"""
tests/test_notice_collection_service.py

services/notice_collection_service.py 테스트.
순수 파싱/필터링 함수는 DB 없이, backfill_notice_categories는
conftest.db_session(SAVEPOINT 롤백) 위에서 검증한다.
"""

import json
from datetime import date, datetime

import pytest

from app.models.notice import Notice
from app.models.notice_source import NoticeSource
from app.models.raw import BizinfoRaw, KstartupRaw
from app.repositories.notice_repository import (
    get_notices_for_status_refresh,
    upsert_notice,
)
from app.services import notice_collection_service as svc
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
    refresh_notice_statuses,
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


# ---------------------------------------------------------------------------
# refresh_notice_statuses (DB 기반)
# ---------------------------------------------------------------------------


async def test_refresh_closes_notice_whose_end_date_has_passed(db_session):
    source = await _create_source(db_session, "상태갱신_마감")
    notice_id = await upsert_notice(
        db_session,
        source_id=source.id,
        external_id="refresh-closed",
        title="마감됐어야 하는 공고",
        application_start_date=date(2020, 1, 1),
        application_end_date=date(2020, 1, 31),
        status="모집중",
        is_actionable=True,
        source_url=None,
        apply_url=None,
        summary_text=None,
    )

    result = await refresh_notice_statuses(db_session)

    notice = await db_session.get(Notice, notice_id)
    assert notice.status == "마감"
    assert notice.is_actionable is False
    assert result["updated"] >= 1


async def test_refresh_leaves_open_notice_untouched(db_session):
    source = await _create_source(db_session, "상태갱신_모집중유지")
    notice_id = await upsert_notice(
        db_session,
        source_id=source.id,
        external_id="refresh-open",
        title="아직 열려있는 공고",
        application_start_date=date(2020, 1, 1),
        application_end_date=date(2099, 1, 1),
        status="모집중",
        is_actionable=True,
        source_url=None,
        apply_url=None,
        summary_text=None,
    )

    await refresh_notice_statuses(db_session)

    notice = await db_session.get(Notice, notice_id)
    assert notice.status == "모집중"
    assert notice.is_actionable is True


async def test_refresh_does_not_downgrade_rolling_open_notice_to_확인필요(db_session):
    """종료일 없는 상시모집 공고는 raw_period 정보 없이 재계산하면 '확인필요'로
    잘못 떨어지므로, 기존 '모집중'을 그대로 유지해야 한다."""
    source = await _create_source(db_session, "상태갱신_상시모집")
    notice_id = await upsert_notice(
        db_session,
        source_id=source.id,
        external_id="refresh-rolling",
        title="상시모집 공고",
        application_start_date=None,
        application_end_date=None,
        status="모집중",
        is_actionable=True,
        source_url=None,
        apply_url=None,
        summary_text=None,
    )

    await refresh_notice_statuses(db_session)

    notice = await db_session.get(Notice, notice_id)
    assert notice.status == "모집중"


async def test_refresh_skips_already_closed_notices(db_session):
    source = await _create_source(db_session, "상태갱신_이미마감")
    notice_id = await upsert_notice(
        db_session,
        source_id=source.id,
        external_id="refresh-already-closed",
        title="이미 마감 처리된 공고",
        application_start_date=date(2020, 1, 1),
        application_end_date=date(2020, 1, 31),
        status="마감",
        is_actionable=False,
        source_url=None,
        apply_url=None,
        summary_text=None,
    )

    rows = await get_notices_for_status_refresh(db_session)

    assert notice_id not in {row[0] for row in rows}


# ---------------------------------------------------------------------------
# 조기종료 판단 (순수 함수 — DB/외부 API 없이 검증)
#
# collect_all_bizinfo_notices/collect_all_kstartup_notices 자체는 소스명이
# "기업마당"/"K-Startup"으로 고정돼 있어, 라이브 검증에 이미 실제 데이터가
# 쌓인 개발 DB에서는 그 실제 데이터가 조기종료 커서에 섞여 들어가 격리된
# 단위 테스트가 불가능하다 (예: get_max_notice_external_id가 테스트가
# 만든 값이 아니라 오늘 실제로 수집된 179xxx대 값을 집어버림). 그래서
# 조기종료 "판단 로직"만 순수 함수로 뽑아 따로 검증하고, 전체 파이프라인
# 동작은 실제 API로 라이브 검증했다(기업마당 1페이지, K-Startup 2페이지
# 만에 조기종료 확인함).
# ---------------------------------------------------------------------------


def test_bizinfo_item_before_cutoff_true_when_older_than_stop_before():
    item = {"creatPnttm": "2026-06-01 10:00:00"}
    stop_before = datetime(2026, 6, 30, 0, 0, 0)

    assert svc._bizinfo_item_before_cutoff(item, stop_before) is True


def test_bizinfo_item_before_cutoff_false_within_buffer_window():
    """stop_before보다 늦으면(버퍼 안) 아직 다시 확인해야 할 대상이다."""
    item = {"creatPnttm": "2026-06-30 12:00:00"}
    stop_before = datetime(2026, 6, 30, 0, 0, 0)

    assert svc._bizinfo_item_before_cutoff(item, stop_before) is False


def test_bizinfo_item_before_cutoff_false_when_no_cutoff():
    """stop_before가 None이면(첫 수집) 조기종료 대상이 없다."""
    item = {"creatPnttm": "2020-01-01 00:00:00"}

    assert svc._bizinfo_item_before_cutoff(item, None) is False


def test_kstartup_item_before_cutoff_true_when_id_at_or_below_threshold():
    assert svc._kstartup_item_before_cutoff({"pbanc_sn": 800}, 800) is True
    assert svc._kstartup_item_before_cutoff({"pbanc_sn": 700}, 800) is True


def test_kstartup_item_before_cutoff_false_when_id_above_threshold():
    assert svc._kstartup_item_before_cutoff({"pbanc_sn": 900}, 800) is False


def test_kstartup_item_before_cutoff_false_when_no_cutoff():
    assert svc._kstartup_item_before_cutoff({"pbanc_sn": 1}, None) is False


# ---------------------------------------------------------------------------
# 조기종료 커서 조회 함수 (DB 기반, 격리된 source_name으로 검증)
# ---------------------------------------------------------------------------


async def test_get_max_bizinfo_registration_time_none_when_no_notices(db_session):
    from app.repositories.notice_repository import get_max_bizinfo_registration_time

    source = NoticeSource(
        source_name="커서테스트_기업마당1", base_url="https://example.com"
    )
    db_session.add(source)
    await db_session.flush()

    assert await get_max_bizinfo_registration_time(db_session, source.id) is None


async def test_get_max_bizinfo_registration_time_returns_latest_creatpnttm(
    db_session,
):
    """이번 수집이 일부만 성공해도(예: 중간에 실패) 그만큼만 커서가 전진해야
    하므로, notice_source.updated_at이 아니라 실제로 저장된 원본 데이터
    (bizinfo_raw.creatPnttm)에서 최댓값을 구한다."""
    from app.repositories.notice_repository import get_max_bizinfo_registration_time

    source = NoticeSource(
        source_name="커서테스트_기업마당2", base_url="https://example.com"
    )
    db_session.add(source)
    await db_session.flush()

    for external_id, creat_pnttm in (
        ("biz-1", "2026-07-01 10:00:00"),
        ("biz-2", "2026-07-05 09:00:00"),  # 가장 최신
        ("biz-3", "2026-07-03 12:00:00"),
    ):
        notice_id = await upsert_notice(
            db_session,
            source_id=source.id,
            external_id=external_id,
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
                key=external_id,
                field=json.dumps({"creatPnttm": creat_pnttm}),
                notice_id=notice_id,
            )
        )
    await db_session.flush()

    result = await get_max_bizinfo_registration_time(db_session, source.id)

    assert result == datetime(2026, 7, 5, 9, 0, 0)


async def test_get_max_notice_external_id_none_when_no_notices(db_session):
    from app.repositories.notice_repository import get_max_notice_external_id

    source = NoticeSource(
        source_name="커서테스트_케이스타트업1", base_url="https://example.com"
    )
    db_session.add(source)
    await db_session.flush()

    assert await get_max_notice_external_id(db_session, source.id) is None


async def test_get_max_notice_external_id_returns_largest_numeric_id(db_session):
    from app.repositories.notice_repository import get_max_notice_external_id

    source = NoticeSource(
        source_name="커서테스트_케이스타트업2", base_url="https://example.com"
    )
    db_session.add(source)
    await db_session.flush()
    for external_id in ("100", "500", "300"):
        await upsert_notice(
            db_session,
            source_id=source.id,
            external_id=external_id,
            title="테스트 공고",
            application_start_date=None,
            application_end_date=None,
            status="모집중",
            is_actionable=True,
            source_url=None,
            apply_url=None,
            summary_text=None,
        )

    assert await get_max_notice_external_id(db_session, source.id) == 500

"""
tests/test_notice_repository.py

repositories/notice_repository.py의 공고(notice) 관련 함수 테스트.
conftest.db_session(SAVEPOINT 롤백) 위에서 실제 DB로 검증한다.
"""

from datetime import date, datetime

import pytest

from app.models.notice import Notice, NoticeAttachment
from app.models.notice_source import NoticeSource
from app.models.raw import BizinfoRaw, KstartupRaw
from app.repositories.notice_repository import (
    delete_notice,
    find_notice_ids_by_source_and_title,
    find_notice_ids_by_source_title_and_dates,
    get_collection_stats,
    get_notice_attachment,
    get_notice_attachments,
    get_notice_attachments_by_ids,
    get_notice_detail,
    get_notice_regions,
    get_notice_regions_by_ids,
    get_notice_target_types,
    get_notices_missing_category,
    get_or_create_organization,
    get_or_create_source,
    list_notices,
    replace_notice_region,
    replace_notice_target_type,
    save_attachment,
    set_attachment_parsed_text,
    set_notice_category,
    update_notice_normalization,
    upsert_notice,
)

pytestmark = pytest.mark.anyio

_FUND_CATEGORY_ID = 1  # kg_category 시드 데이터 기준 "자금"


async def _create_source(db_session, name: str) -> NoticeSource:
    source = NoticeSource(source_name=name, base_url="https://example.com")
    db_session.add(source)
    await db_session.flush()
    return source


async def _create_notice(db_session, source: NoticeSource, **overrides) -> int:
    defaults = dict(
        source_id=source.id,
        external_id="ext-1",
        title="테스트 공고",
        application_start_date=None,
        application_end_date=None,
        status="모집중",
        is_actionable=True,
        source_url=None,
        apply_url=None,
        summary_text=None,
    )
    defaults.update(overrides)
    return await upsert_notice(db_session, **defaults)


# ---------------------------------------------------------------------------
# get_or_create_source / get_or_create_organization
# ---------------------------------------------------------------------------


async def test_get_or_create_source_is_idempotent(db_session):
    first = await get_or_create_source(
        db_session,
        source_name="중복테스트출처",
        base_url="https://a.com",
        collect_type="API",
    )
    second = await get_or_create_source(
        db_session,
        source_name="중복테스트출처",
        base_url="https://b.com",
        collect_type="API",
    )

    assert first.id == second.id
    assert second.base_url == "https://b.com"  # DO UPDATE로 최신 값 반영


async def test_get_or_create_organization_is_idempotent(db_session):
    first = await get_or_create_organization(db_session, "테스트기관")
    second = await get_or_create_organization(db_session, "테스트기관")

    assert first.id == second.id


# ---------------------------------------------------------------------------
# upsert_notice
# ---------------------------------------------------------------------------


async def test_upsert_notice_rejects_empty_external_id(db_session):
    source = await _create_source(db_session, "빈external_id출처")
    with pytest.raises(ValueError):
        await upsert_notice(
            db_session,
            source_id=source.id,
            external_id="",
            title="제목",
            application_start_date=None,
            application_end_date=None,
            status=None,
            is_actionable=None,
            source_url=None,
            apply_url=None,
            summary_text=None,
        )


async def test_upsert_notice_dedupes_by_source_and_external_id(db_session):
    source = await _create_source(db_session, "중복공고출처")

    first_id = await _create_notice(
        db_session, source, external_id="dup-1", title="원래 제목"
    )
    second_id = await _create_notice(
        db_session, source, external_id="dup-1", title="수정된 제목"
    )

    assert first_id == second_id
    notice = await db_session.get(Notice, first_id)
    assert notice.title == "수정된 제목"


async def test_upsert_notice_stores_category_id(db_session):
    source = await _create_source(db_session, "카테고리저장출처")

    notice_id = await _create_notice(
        db_session, source, external_id="cat-1", category_id=_FUND_CATEGORY_ID
    )

    notice = await db_session.get(Notice, notice_id)
    assert notice.category_id == _FUND_CATEGORY_ID


# ---------------------------------------------------------------------------
# set_notice_category / get_notices_missing_category
# ---------------------------------------------------------------------------


async def test_set_notice_category_updates_existing_notice(db_session):
    source = await _create_source(db_session, "카테고리업데이트출처")
    notice_id = await _create_notice(db_session, source, external_id="upd-1")

    await set_notice_category(db_session, notice_id, _FUND_CATEGORY_ID)

    notice = await db_session.get(Notice, notice_id)
    assert notice.category_id == _FUND_CATEGORY_ID


async def test_get_notices_missing_category_only_returns_null_category_rows(
    db_session,
):
    source = await _create_source(db_session, "백필대상출처")
    missing_id = await _create_notice(db_session, source, external_id="missing-1")
    filled_id = await _create_notice(
        db_session, source, external_id="filled-1", category_id=_FUND_CATEGORY_ID
    )
    db_session.add(BizinfoRaw(key="missing-1", field="{}", notice_id=missing_id))
    db_session.add(BizinfoRaw(key="filled-1", field="{}", notice_id=filled_id))
    await db_session.flush()

    rows = await get_notices_missing_category(db_session, BizinfoRaw)
    notice_ids = {notice_id for notice_id, _ in rows}

    assert missing_id in notice_ids
    assert filled_id not in notice_ids


async def test_get_notices_missing_category_scoped_to_given_raw_model(db_session):
    """BizinfoRaw로 조회하면 KstartupRaw에만 연결된 공고는 나오지 않는다."""
    source = await _create_source(db_session, "출처구분테스트")
    ks_notice_id = await _create_notice(db_session, source, external_id="ks-only")
    db_session.add(KstartupRaw(key="ks-only", field="{}", notice_id=ks_notice_id))
    await db_session.flush()

    rows = await get_notices_missing_category(db_session, BizinfoRaw)

    assert ks_notice_id not in {notice_id for notice_id, _ in rows}


# ---------------------------------------------------------------------------
# find_notice_ids_by_source_and_title / find_notice_ids_by_source_title_and_dates
# / delete_notice
# ---------------------------------------------------------------------------


async def test_find_notice_ids_by_source_and_title_matches_regardless_of_dates(
    db_session,
):
    """신청기간이 아예 없는 공고(실제 DB 확인: 기업마당의 89%가 "상시모집"
    등으로 신청기간이 없음)도 제목만으로는 찾을 수 있어야 한다 — 날짜를
    무조건 요구하는 건 find_notice_ids_by_source_title_and_dates 쪽 책임이고,
    이 함수는 순수하게 제목만 본다."""
    source = await _create_source(db_session, "날짜없는공고출처")
    notice_id = await _create_notice(
        db_session,
        source,
        external_id="no-date-1",
        title="상시모집 공고",
        application_start_date=None,
        application_end_date=None,
    )

    found = await find_notice_ids_by_source_and_title(
        db_session, "날짜없는공고출처", "상시모집 공고"
    )

    assert found == [notice_id]


async def test_find_notice_ids_by_source_title_and_dates_matches_exact_title_and_dates(
    db_session,
):
    source = await _create_source(db_session, "제목검색출처")
    notice_id = await _create_notice(
        db_session,
        source,
        external_id="title-1",
        title="정확히 일치하는 제목",
        application_start_date=date(2026, 1, 1),
        application_end_date=date(2026, 1, 31),
    )

    found = await find_notice_ids_by_source_title_and_dates(
        db_session,
        "제목검색출처",
        "정확히 일치하는 제목",
        date(2026, 1, 1),
        date(2026, 1, 31),
    )
    not_found_by_title = await find_notice_ids_by_source_title_and_dates(
        db_session, "제목검색출처", "다른 제목", date(2026, 1, 1), date(2026, 1, 31)
    )

    assert found == [notice_id]
    assert not_found_by_title == []


async def test_find_notice_ids_by_source_title_and_dates_ignores_same_title_different_round(
    db_session,
):
    """같은 출처 안에서도 제목이 같은 공고가 여러 건일 수 있다(실제 DB에서
    확인: 매달 반복되는 K-Startup 모집 공고가 제목을 그대로 재사용해,
    신청기간이 전혀 안 겹치는 회차 8개가 완전히 같은 제목으로 존재).
    제목만 보고 매칭하면 지금 회차와 무관한 다른 회차까지 중복으로
    오인하므로, 신청기간까지 같아야 매칭돼야 한다."""
    source = await _create_source(db_session, "복수제목출처")
    this_round = await _create_notice(
        db_session,
        source,
        external_id="round-2",
        title="반복되는 모집 공고",
        application_start_date=date(2026, 3, 1),
        application_end_date=date(2026, 3, 31),
    )
    await _create_notice(
        db_session,
        source,
        external_id="round-1",
        title="반복되는 모집 공고",
        application_start_date=date(2026, 1, 1),
        application_end_date=date(2026, 1, 31),
    )

    found = await find_notice_ids_by_source_title_and_dates(
        db_session,
        "복수제목출처",
        "반복되는 모집 공고",
        date(2026, 3, 1),
        date(2026, 3, 31),
    )

    assert found == [this_round]


async def test_delete_notice_removes_related_rows(db_session):
    source = await _create_source(db_session, "삭제테스트출처")
    notice_id = await _create_notice(db_session, source, external_id="del-1")
    db_session.add(BizinfoRaw(key="del-1", field="{}", notice_id=notice_id))
    await replace_notice_target_type(db_session, notice_id, ["소상공인"])
    await replace_notice_region(db_session, notice_id, [("11", "서울")])
    await save_attachment(db_session, notice_id, "a.pdf", "https://a.com/a.pdf", "PDF")
    await db_session.flush()

    await delete_notice(db_session, notice_id)
    await db_session.flush()

    assert await db_session.get(Notice, notice_id) is None
    assert await get_notice_target_types(db_session, notice_id) == []
    assert await get_notice_regions(db_session, notice_id) == []
    assert await get_notice_attachments(db_session, notice_id) == []


# ---------------------------------------------------------------------------
# replace_notice_region / replace_notice_target_type
# ---------------------------------------------------------------------------


async def test_replace_notice_region_clears_old_values_when_new_list_empty(
    db_session,
):
    source = await _create_source(db_session, "지역교체출처")
    notice_id = await _create_notice(db_session, source, external_id="region-1")

    await replace_notice_region(db_session, notice_id, [("11", "서울")])
    assert await get_notice_regions(db_session, notice_id) == ["서울"]

    await replace_notice_region(db_session, notice_id, [])
    assert await get_notice_regions(db_session, notice_id) == []


# ---------------------------------------------------------------------------
# save_attachment / set_attachment_parsed_text
# ---------------------------------------------------------------------------


async def test_save_attachment_upsert_does_not_clobber_parsed_text(db_session):
    source = await _create_source(db_session, "첨부재수집출처")
    notice_id = await _create_notice(db_session, source, external_id="attach-1")

    await save_attachment(
        db_session, notice_id, "old_name.pdf", "https://a.com/f.pdf", "PDF"
    )
    attachments = await get_notice_attachments(db_session, notice_id)
    await set_attachment_parsed_text(db_session, attachments[0].id, "OCR 결과 텍스트")

    # 같은 공고를 재수집했을 때 파일명이 바뀌어도 parsed_text는 유지돼야 한다.
    await save_attachment(
        db_session, notice_id, "new_name.pdf", "https://a.com/f.pdf", "PDF"
    )

    # save_attachment는 ORM을 거치지 않는 raw upsert라 세션 identity map이
    # 갱신되지 않는다 — populate_existing으로 DB의 최신 값을 강제로 다시 읽는다.
    reloaded = await db_session.get(
        NoticeAttachment, attachments[0].id, populate_existing=True
    )
    assert reloaded.file_name == "new_name.pdf"
    assert reloaded.parsed_text == "OCR 결과 텍스트"


async def test_set_attachment_parsed_text_returns_true_when_row_updated(db_session):
    source = await _create_source(db_session, "저장성공출처")
    notice_id = await _create_notice(db_session, source, external_id="attach-2")
    await save_attachment(
        db_session, notice_id, "공고문.pdf", "https://a.com/f.pdf", "PDF"
    )
    attachments = await get_notice_attachments(db_session, notice_id)

    saved = await set_attachment_parsed_text(db_session, attachments[0].id, "텍스트")

    assert saved is True


async def test_set_attachment_parsed_text_returns_false_when_attachment_gone(
    db_session,
):
    """다운로드·OCR이 도는 동안 "기업마당 우선 정책"으로 공고 자체가
    cascade 삭제됐다면 attachment_id가 더 이상 존재하지 않는다 — 이 경우
    호출자(notice_ocr)가 COMPLETED로 잘못 보고하지 않도록 False를 반환해야
    한다."""
    saved = await set_attachment_parsed_text(db_session, 999_999_999, "텍스트")

    assert saved is False


async def test_get_notice_attachments_by_ids_batches_multiple_notices(db_session):
    """OCR 배치 트리거(POST /internal/notices/ocr/batch)로 여러 공고를 한 번에
    돌린 뒤, notice_id마다 get_notice_attachments를 따로 호출하지 않고 한
    번에 parsed_text까지 가져올 수 있어야 한다."""
    source = await _create_source(db_session, "첨부배치조회출처")
    notice_a = await _create_notice(db_session, source, external_id="batch-attach-a")
    notice_b = await _create_notice(db_session, source, external_id="batch-attach-b")
    await save_attachment(db_session, notice_a, "a.pdf", "https://a.com/a.pdf", "PDF")
    await save_attachment(db_session, notice_b, "b.pdf", "https://a.com/b.pdf", "PDF")
    attachments_a = await get_notice_attachments(db_session, notice_a)
    await set_attachment_parsed_text(db_session, attachments_a[0].id, "A 원문")

    by_notice = await get_notice_attachments_by_ids(db_session, [notice_a, notice_b])

    assert set(by_notice.keys()) == {notice_a, notice_b}
    assert by_notice[notice_a][0].parsed_text == "A 원문"
    assert by_notice[notice_b][0].parsed_text is None


async def test_get_notice_attachments_by_ids_returns_empty_dict_for_empty_input(
    db_session,
):
    assert await get_notice_attachments_by_ids(db_session, []) == {}


# ---------------------------------------------------------------------------
# get_notice_attachment
# ---------------------------------------------------------------------------


async def test_get_notice_attachment_returns_attachment_with_parsed_text(db_session):
    source = await _create_source(db_session, "단건첨부조회출처")
    notice_id = await _create_notice(db_session, source, external_id="single-attach-1")
    await save_attachment(db_session, notice_id, "a.pdf", "https://a.com/a.pdf", "PDF")
    attachment_id = (await get_notice_attachments(db_session, notice_id))[0].id
    await set_attachment_parsed_text(db_session, attachment_id, "원문 텍스트")

    result = await get_notice_attachment(db_session, notice_id, attachment_id)

    assert result is not None
    assert result.parsed_text == "원문 텍스트"


async def test_get_notice_attachment_returns_none_for_mismatched_notice_id(
    db_session,
):
    """attachment_id는 notice에 종속된 자원이라, 다른 공고의 notice_id로
    조회하면 실제로 존재하는 attachment_id여도 None이어야 한다."""
    source = await _create_source(db_session, "단건첨부조회출처2")
    notice_id = await _create_notice(db_session, source, external_id="single-attach-2")
    await save_attachment(db_session, notice_id, "a.pdf", "https://a.com/a.pdf", "PDF")
    attachment_id = (await get_notice_attachments(db_session, notice_id))[0].id

    result = await get_notice_attachment(db_session, 999_999_999, attachment_id)

    assert result is None


# ---------------------------------------------------------------------------
# get_collection_stats
# ---------------------------------------------------------------------------


async def test_get_collection_stats_returns_expected_keys(db_session):
    stats = await get_collection_stats(db_session)

    assert set(stats.keys()) == {
        "by_source",
        "by_category",
        "by_status",
        "ocr_pending_count",
        "by_normalization_status",
    }
    assert isinstance(stats["ocr_pending_count"], int)


async def test_get_collection_stats_counts_unparsed_ocr_target_attachment(db_session):
    source = await _create_source(db_session, "통계테스트출처")
    notice_id = await _create_notice(db_session, source, external_id="stats-1")
    before = await get_collection_stats(db_session)

    await save_attachment(db_session, notice_id, "a.pdf", "https://a.com/a.pdf", "PDF")

    after = await get_collection_stats(db_session)

    assert after["ocr_pending_count"] == before["ocr_pending_count"] + 1
    assert after["by_source"][source.source_name] == 1
    assert after["by_status"]["모집중"] >= 1


async def test_get_collection_stats_excludes_notice_once_parsed(db_session):
    source = await _create_source(db_session, "통계테스트출처2")
    notice_id = await _create_notice(db_session, source, external_id="stats-2")
    await save_attachment(db_session, notice_id, "a.pdf", "https://a.com/a.pdf", "PDF")
    before = await get_collection_stats(db_session)

    attachment_id = (await get_notice_attachments(db_session, notice_id))[0].id
    await set_attachment_parsed_text(db_session, attachment_id, "원문")

    after = await get_collection_stats(db_session)

    assert after["ocr_pending_count"] == before["ocr_pending_count"] - 1


async def test_get_collection_stats_buckets_normalization_status(db_session):
    before = await get_collection_stats(db_session)

    source = await _create_source(db_session, "통계테스트출처3")
    notice_id = await _create_notice(db_session, source, external_id="stats-3")

    # normalization_status가 NULL인 새 공고는 not_started로 잡혀야 한다.
    after_created = await get_collection_stats(db_session)
    assert (
        after_created["by_normalization_status"]["not_started"]
        == before["by_normalization_status"].get("not_started", 0) + 1
    )

    await update_notice_normalization(
        db_session,
        notice_id,
        normalized_json={"basic": {"title": "t"}},
        normalization_status="completed",
        normalization_error=None,
        normalized_at=datetime.now(),
    )

    after_completed = await get_collection_stats(db_session)
    assert (
        after_completed["by_normalization_status"]["completed"]
        == before["by_normalization_status"].get("completed", 0) + 1
    )
    # CI처럼 다른 공고가 전혀 없는 DB에서는 이 공고가 completed로 바뀌면서
    # not_started 버킷 자체가 사라질 수 있다(0이면 GROUP BY 결과에 행이 안
    # 나옴) — 그래서 직접 인덱싱 대신 .get(..., 0)으로 확인한다.
    assert after_completed["by_normalization_status"].get("not_started", 0) == before[
        "by_normalization_status"
    ].get("not_started", 0)


# ---------------------------------------------------------------------------
# list_notices
# ---------------------------------------------------------------------------


async def test_list_notices_filters_by_source_and_excludes_closed_by_default(
    db_session,
):
    biz_source = await _create_source(db_session, "목록조회_기업마당")
    ks_source = await _create_source(db_session, "목록조회_K-Startup")

    open_id = await _create_notice(
        db_session, biz_source, external_id="list-open", status="모집중"
    )
    await _create_notice(
        db_session, biz_source, external_id="list-closed", status="마감"
    )
    await _create_notice(db_session, ks_source, external_id="list-other-source")

    rows, total = await list_notices(
        db_session, source_name="목록조회_기업마당", exclude_closed=True
    )

    assert total == 1
    assert rows[0][0].id == open_id


async def test_list_notices_includes_closed_when_flag_disabled(db_session):
    source = await _create_source(db_session, "목록조회_마감포함")
    await _create_notice(db_session, source, external_id="closed-1", status="마감")

    rows, total = await list_notices(
        db_session, source_name="목록조회_마감포함", exclude_closed=False
    )

    assert total == 1
    assert rows[0][0].status == "마감"


async def test_list_notices_filters_by_category_name(db_session):
    source = await _create_source(db_session, "목록조회_카테고리")
    fund_id = await _create_notice(
        db_session, source, external_id="cat-fund", category_id=_FUND_CATEGORY_ID
    )
    await _create_notice(db_session, source, external_id="cat-none")

    rows, total = await list_notices(
        db_session, source_name="목록조회_카테고리", category_name="자금"
    )

    assert total == 1
    assert rows[0][0].id == fund_id


# ---------------------------------------------------------------------------
# get_notice_detail / get_notice_regions_by_ids
# ---------------------------------------------------------------------------


async def test_get_notice_detail_returns_none_when_missing(db_session):
    assert await get_notice_detail(db_session, 999_999) is None


async def test_get_notice_detail_returns_notice_source_and_category(db_session):
    source = await _create_source(db_session, "상세조회출처")
    notice_id = await _create_notice(
        db_session, source, external_id="detail-1", category_id=_FUND_CATEGORY_ID
    )

    row = await get_notice_detail(db_session, notice_id)

    assert row is not None
    notice, source_name, category_name = row
    assert notice.id == notice_id
    assert source_name == "상세조회출처"
    assert category_name == "자금"


async def test_get_notice_regions_by_ids_batches_multiple_notices(db_session):
    source = await _create_source(db_session, "지역배치조회출처")
    notice_a = await _create_notice(db_session, source, external_id="region-a")
    notice_b = await _create_notice(db_session, source, external_id="region-b")
    await replace_notice_region(db_session, notice_a, [("11", "서울")])
    await replace_notice_region(db_session, notice_b, [("26", "부산")])

    regions = await get_notice_regions_by_ids(db_session, [notice_a, notice_b])

    assert regions == {notice_a: ["서울"], notice_b: ["부산"]}


async def test_get_notice_regions_by_ids_returns_empty_dict_for_empty_input(
    db_session,
):
    assert await get_notice_regions_by_ids(db_session, []) == {}

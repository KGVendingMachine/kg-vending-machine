"""
tests/test_notice_router.py

api/notice.py(공고 목록/상세 조회) 테스트. 라우터 함수를 직접 호출한다.
Query(...) 기본값 객체가 그대로 전달되는 걸 피하기 위해 모든 쿼리
파라미터에 명시적으로 값을 넘긴다.
"""

import pytest
from fastapi import HTTPException

from app.api.notice import _amount_label, _summary_text, get_notice, get_notices
from app.models.notice import Notice
from app.models.notice_source import NoticeSource
from app.repositories.notice_repository import replace_notice_region, upsert_notice

pytestmark = pytest.mark.anyio

_FUND_CATEGORY_ID = 1  # kg_category 시드 데이터 기준 "자금"


def test_amount_label_falls_back_to_normalized_support_amount():
    notice = Notice(
        amount_label=None,
        normalized_json={"support": {"support_amount": "기업당 최대 1억원"}},
    )

    assert _amount_label(notice) == "기업당 최대 1억원"


def test_amount_label_prefers_source_amount_label():
    notice = Notice(
        amount_label="최대 5천만원",
        normalized_json={"support": {"support_amount": "기업당 최대 1억원"}},
    )

    assert _amount_label(notice) == "최대 5천만원"


def test_summary_text_falls_back_to_normalized_support_summary():
    notice = Notice(
        summary_text="source summary",
        normalized_json={"support": {"summary": "normalized summary"}},
    )

    assert _summary_text(notice) == "normalized summary"


def test_summary_text_uses_source_summary_when_normalized_summary_missing():
    notice = Notice(summary_text="source summary", normalized_json={"support": {}})

    assert _summary_text(notice) == "source summary"


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
        source_url="https://example.com/notice/1",
        apply_url=None,
        summary_text=None,
    )
    defaults.update(overrides)
    return await upsert_notice(db_session, **defaults)


async def test_get_notices_returns_summaries_with_regions(db_session):
    source = await _create_source(db_session, "목록API_출처")
    notice_id = await _create_notice(
        db_session, source, external_id="api-list-1", category_id=_FUND_CATEGORY_ID
    )
    await replace_notice_region(db_session, notice_id, [("11", "서울")])

    response = await get_notices(
        source="목록API_출처",
        category=None,
        region_code=None,
        exclude_closed=True,
        limit=20,
        offset=0,
        session=db_session,
    )

    assert response.total == 1
    item = response.items[0]
    assert item.id == notice_id
    assert item.source == "목록API_출처"
    assert item.category == "자금"
    assert item.regions == ["서울"]


async def test_get_notices_excludes_closed_by_default(db_session):
    source = await _create_source(db_session, "목록API_마감제외")
    await _create_notice(db_session, source, external_id="api-closed", status="마감")

    response = await get_notices(
        source="목록API_마감제외",
        category=None,
        region_code=None,
        exclude_closed=True,
        limit=20,
        offset=0,
        session=db_session,
    )

    assert response.total == 0


async def test_get_notice_returns_detail_with_attachments(db_session):
    source = await _create_source(db_session, "상세API_출처")
    notice_id = await _create_notice(db_session, source, external_id="api-detail-1")

    detail = await get_notice(notice_id, session=db_session)

    assert detail.id == notice_id
    assert detail.source == "상세API_출처"
    assert detail.attachments == []
    assert detail.regions == []


async def test_get_notice_404_when_missing(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await get_notice(999_999, session=db_session)

    assert exc_info.value.status_code == 404

"""북마크 비즈니스 로직.

우리 공고는 '특정 사업계획서로 매칭한 결과'로 등장하므로, 추천 카드에서 담을
땐 그 맥락(공고·사업계획서·추천 근거)을 함께 얼려 저장한다. 목록 조회 시에는
각 북마크의 기반 사업계획서가 현재 최신 계획서와 다른지(stale)를 계산해 준다.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notice import Notice
from app.models.user import User
from app.repositories import (
    company_repository,
    match_log_repository,
    notice_bookmark_repository,
)
from app.repositories.business_plan_repository import get_latest_by_company_profile
from app.repositories.notice_bookmark_repository import BookmarkListRow
from app.schemas.notice_bookmark import (
    BookmarkCreateRequest,
    BookmarkNoticeInfo,
    BookmarkRecommendation,
    BookmarkResponse,
)

SOURCE_RECOMMENDATION = "recommendation"
SOURCE_BROWSE = "browse"


class BookmarkTargetNotFoundError(Exception):
    """담으려는 공고/추천 결과가 없거나 본인 것이 아닐 때."""


async def _current_plan_id(session: AsyncSession, user_id: int) -> int | None:
    """stale 판정 기준이 되는 '유저의 현재 최신 사업계획서 id'."""
    profile = await company_repository.get_primary_by_user(session, user_id)
    if profile is None:
        return None
    latest = await get_latest_by_company_profile(session, profile.id)
    return latest.id if latest else None


def _to_response(row: BookmarkListRow, *, current_plan_id: int | None) -> BookmarkResponse:
    bm = row.bookmark
    is_stale = (
        bm.business_plan_id is not None
        and current_plan_id is not None
        and bm.business_plan_id != current_plan_id
    )
    recommendation = (
        BookmarkRecommendation(
            total_score=row.total_score,
            recommendation_level=row.recommendation_level,
            summary_reason=row.summary_reason,
        )
        if bm.source == SOURCE_RECOMMENDATION
        else None
    )
    return BookmarkResponse(
        id=bm.id,
        source=bm.source,
        business_plan_id=bm.business_plan_id,
        business_plan_title=row.business_plan_title,
        is_stale=is_stale,
        notice=BookmarkNoticeInfo(
            id=row.notice.id,
            title=row.notice.title,
            organization_name=row.organization_name,
            category_name=row.category_name,
            status=row.notice.status,
            application_end_date=row.notice.application_end_date,
            amount_label=row.notice.amount_label,
            source_url=row.notice.source_url,
            apply_url=row.notice.apply_url,
        ),
        recommendation=recommendation,
        created_at=bm.created_at,
    )


async def add_bookmark(
    session: AsyncSession, *, user: User, req: BookmarkCreateRequest
) -> BookmarkResponse:
    """북마크를 담고 카드 표현으로 돌려준다(이미 있으면 기존 것을 그대로).

    추천 카드(match_result_id)면 공고·사업계획서 맥락을 결과에서 끌어와 함께
    저장한다. 브라우징(notice_id)이면 사업계획서 맥락 없이 공고만 담는다.
    """
    if req.match_result_id is not None:
        result = await match_log_repository.get_result_owned_by_user(
            session, req.match_result_id, user.id
        )
        if result is None:
            raise BookmarkTargetNotFoundError()
        notice_id = result.notice_id
        business_plan_id = await match_log_repository.get_business_plan_id_for_result(
            session, req.match_result_id
        )
        match_result_id: int | None = req.match_result_id
        source = SOURCE_RECOMMENDATION
    else:
        notice = await session.get(Notice, req.notice_id)
        if notice is None:
            raise BookmarkTargetNotFoundError()
        notice_id = notice.id
        business_plan_id = None
        match_result_id = None
        source = SOURCE_BROWSE

    bookmark = await notice_bookmark_repository.add(
        session,
        user_id=user.id,
        notice_id=notice_id,
        business_plan_id=business_plan_id,
        match_result_id=match_result_id,
        source=source,
    )
    await session.commit()

    row = await notice_bookmark_repository.get_row_by_id(
        session, bookmark_id=bookmark.id, user_id=user.id
    )
    # 방금 만든 행이라 반드시 존재한다.
    assert row is not None
    current_plan_id = await _current_plan_id(session, user.id)
    return _to_response(row, current_plan_id=current_plan_id)


async def remove_bookmark(
    session: AsyncSession, *, user: User, bookmark_id: int
) -> bool:
    """본인 북마크 한 건을 삭제한다. 없거나 남의 것이면 False."""
    deleted = await notice_bookmark_repository.delete_by_id(
        session, bookmark_id=bookmark_id, user_id=user.id
    )
    if deleted:
        await session.commit()
    return deleted


async def list_bookmarks(
    session: AsyncSession, *, user: User
) -> list[BookmarkResponse]:
    """유저의 북마크를 최신순으로, 각 항목의 stale 여부와 함께 반환한다."""
    rows = await notice_bookmark_repository.list_by_user(session, user.id)
    current_plan_id = await _current_plan_id(session, user.id)
    return [_to_response(row, current_plan_id=current_plan_id) for row in rows]

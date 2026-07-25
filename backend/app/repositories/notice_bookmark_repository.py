"""notice_bookmark 테이블 접근 계층.

커밋은 하지 않고 호출하는 서비스가 트랜잭션 경계를 관리한다(다른 repository와
동일 규칙). 리스트 조회는 카드 표시에 필요한 공고 요약·사업계획서 제목·담을
당시 추천 근거(match_result)를 함께 돌려준다.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_plan import BusinessPlan
from app.models.category import KgCategory
from app.models.match import MatchResult
from app.models.notice import Notice
from app.models.notice_bookmark import NoticeBookmark
from app.models.organization import Organization


@dataclass(frozen=True)
class BookmarkListRow:
    """북마크 목록 한 행. 공고 요약과 담을 당시 추천 근거를 함께 담는다."""

    bookmark: NoticeBookmark
    notice: Notice
    organization_name: str | None
    category_name: str | None
    business_plan_title: str | None
    total_score: Decimal | None
    recommendation_level: str | None
    summary_reason: str | None


async def add(
    session: AsyncSession,
    *,
    user_id: int,
    notice_id: int,
    business_plan_id: int | None,
    match_result_id: int | None,
    source: str,
) -> NoticeBookmark:
    """북마크를 담고 그 행을 반환한다.

    이미 (user, notice, plan) 이 있으면 DO NOTHING 으로 담을 당시 상황을 보존한
    뒤 기존 행을 그대로 돌려준다(멱등). 커밋은 호출자가 한다.
    """
    stmt = (
        pg_insert(NoticeBookmark)
        .values(
            user_id=user_id,
            notice_id=notice_id,
            business_plan_id=business_plan_id,
            match_result_id=match_result_id,
            source=source,
        )
        .on_conflict_do_nothing(constraint="uq_bookmark_user_notice_plan")
    )
    await session.execute(stmt)
    await session.flush()

    plan_predicate = (
        NoticeBookmark.business_plan_id.is_(None)
        if business_plan_id is None
        else NoticeBookmark.business_plan_id == business_plan_id
    )
    result = await session.execute(
        select(NoticeBookmark).where(
            NoticeBookmark.user_id == user_id,
            NoticeBookmark.notice_id == notice_id,
            plan_predicate,
        )
    )
    return result.scalar_one()


async def delete_by_id(
    session: AsyncSession, *, bookmark_id: int, user_id: int
) -> bool:
    """본인 북마크 한 건을 삭제한다. 삭제 성공 여부를 반환한다(커밋은 호출자).

    소유자 확인을 WHERE 에 함께 걸어 남의 북마크는 건드리지 못하게 한다.
    """
    bookmark = await session.get(NoticeBookmark, bookmark_id)
    if bookmark is None or bookmark.user_id != user_id:
        return False
    await session.delete(bookmark)
    await session.flush()
    return True


def _rows_query():
    """북마크 + 카드 표시값(공고 요약·계획서 제목·추천 근거) 조인 select.

    목록 조회와 단건 조회가 같은 표현을 쓰도록 공유한다.
    """
    return (
        select(
            NoticeBookmark,
            Notice,
            Organization.name,
            KgCategory.name,
            BusinessPlan.title,
            MatchResult.total_score,
            MatchResult.recommendation_level,
            MatchResult.summary_reason,
        )
        .join(Notice, Notice.id == NoticeBookmark.notice_id)
        .join(Organization, Notice.organization_id == Organization.id, isouter=True)
        .join(KgCategory, Notice.category_id == KgCategory.id, isouter=True)
        .join(
            BusinessPlan,
            BusinessPlan.id == NoticeBookmark.business_plan_id,
            isouter=True,
        )
        .join(
            MatchResult,
            MatchResult.id == NoticeBookmark.match_result_id,
            isouter=True,
        )
    )


def _to_row(row) -> BookmarkListRow:
    return BookmarkListRow(
        bookmark=row[0],
        notice=row[1],
        organization_name=row[2],
        # KgCategory.name 은 Enum 컬럼이라 멤버로 올 수 있어 표시값으로 푼다.
        category_name=getattr(row[3], "value", row[3]),
        business_plan_title=row[4],
        total_score=row[5],
        recommendation_level=row[6],
        summary_reason=row[7],
    )


async def get_row_by_id(
    session: AsyncSession, *, bookmark_id: int, user_id: int
) -> BookmarkListRow | None:
    """본인 북마크 한 건을 카드 표시값과 함께 반환한다. 없으면 None."""
    result = await session.execute(
        _rows_query().where(
            NoticeBookmark.id == bookmark_id,
            NoticeBookmark.user_id == user_id,
        )
    )
    row = result.one_or_none()
    return _to_row(row) if row is not None else None


async def list_by_user(session: AsyncSession, user_id: int) -> list[BookmarkListRow]:
    """유저의 북마크를 최신순으로, 카드 표시에 필요한 값과 함께 반환한다."""
    result = await session.execute(
        _rows_query()
        .where(NoticeBookmark.user_id == user_id)
        .order_by(NoticeBookmark.created_at.desc(), NoticeBookmark.id.desc())
    )
    return [_to_row(row) for row in result.all()]

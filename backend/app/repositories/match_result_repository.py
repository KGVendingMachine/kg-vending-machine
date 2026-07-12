"""match_result 테이블 접근 계층.

커밋은 하지 않고 호출하는 쪽이 트랜잭션 경계를 관리한다(match_log_repository와
동일 규칙). 조회는 결과 페이지 표시에 필요한 공고 정보(제목·기관·카테고리 등)를
함께 돌려준다.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import KgCategory
from app.models.match import MatchResult
from app.models.notice import Notice
from app.models.organization import Organization


async def create_many(
    session: AsyncSession, match_log_id: int, rows: list[dict]
) -> list[MatchResult]:
    """한 매칭 실행의 결과 행들을 일괄 생성한다. flush만 하고 커밋은 안 한다.

    rows의 각 dict는 MatchResult 컬럼(notice_id, total_score, ...)을 담는다.
    """
    results = [MatchResult(recommendation_run_id=match_log_id, **row) for row in rows]
    session.add_all(results)
    await session.flush()
    return results


@dataclass(frozen=True)
class MatchResultWithNotice:
    result: MatchResult
    notice: Notice
    organization_name: str | None
    category_name: str | None


async def list_by_match_log(
    session: AsyncSession, match_log_id: int
) -> list[MatchResultWithNotice]:
    """한 매칭 실행의 결과들을 적합도 내림차순으로, 공고 정보와 함께 반환한다."""
    rows = await session.execute(
        select(MatchResult, Notice, Organization.name, KgCategory.name)
        .join(Notice, MatchResult.notice_id == Notice.id)
        .join(Organization, Notice.organization_id == Organization.id, isouter=True)
        .join(KgCategory, Notice.category_id == KgCategory.id, isouter=True)
        .where(MatchResult.recommendation_run_id == match_log_id)
        .order_by(MatchResult.total_score.desc().nulls_last(), MatchResult.id)
    )
    items: list[MatchResultWithNotice] = []
    for result, notice, org_name, category_name in rows.all():
        items.append(
            MatchResultWithNotice(
                result=result,
                notice=notice,
                organization_name=org_name,
                # KgCategory.name은 Enum 컬럼이라 멤버로 올 수 있어 표시값으로 푼다.
                category_name=getattr(category_name, "value", category_name),
            )
        )
    return items


async def pick_stub_notices(session: AsyncSession, limit: int) -> list[Notice]:
    """스코어링 스텁이 평가 대상으로 쓸 공고를 고른다.

    모집중 공고를 최신순으로 우선하고, 부족하면 상태 무관 최신 공고로 채운다.
    실제 스코어링(후보 필터링)이 생기면 이 함수는 대체된다.
    """
    result = await session.execute(
        select(Notice)
        .where(Notice.status == "모집중")
        .order_by(Notice.id.desc())
        .limit(limit)
    )
    notices = list(result.scalars().all())
    if len(notices) < limit:
        filler_stmt = (
            select(Notice).order_by(Notice.id.desc()).limit(limit - len(notices))
        )
        picked_ids = [notice.id for notice in notices]
        if picked_ids:
            filler_stmt = filler_stmt.where(Notice.id.not_in(picked_ids))
        filler = await session.execute(filler_stmt)
        notices.extend(filler.scalars().all())
    return notices

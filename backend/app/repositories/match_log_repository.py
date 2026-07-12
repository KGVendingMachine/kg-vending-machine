"""match_log 테이블 접근 계층.

커밋은 하지 않고 호출하는 쪽이 트랜잭션 경계를 관리한다(company_repository와
동일 규칙). 리스트 조회는 어떤 파일로 돌린 매칭인지 보여줄 수 있게
business_plan.title을 함께 돌려준다.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_plan import BusinessPlan
from app.models.match import MatchLog


async def create(
    session: AsyncSession,
    *,
    user_id: int,
    company_profile_id: int,
    business_plan_id: int,
    run_status: str,
    query_text: str | None = None,
    query_json: dict | None = None,
    completed_at: datetime | None = None,
) -> MatchLog:
    """매칭 실행 로그 한 행을 만든다. flush로 id만 채우고 커밋은 안 한다."""
    log = MatchLog(
        user_id=user_id,
        company_profile_id=company_profile_id,
        business_plan_id=business_plan_id,
        run_status=run_status,
        query_text=query_text,
        query_json=query_json,
        completed_at=completed_at,
    )
    session.add(log)
    await session.flush()
    return log


async def list_by_user(
    session: AsyncSession, user_id: int, *, limit: int = 20, offset: int = 0
) -> list[tuple[MatchLog, str | None]]:
    """유저의 매칭 로그를 최신순으로 (로그, 사업계획서 제목) 쌍으로 반환한다.

    business_plan_id가 NULL인 행도 있을 수 있어(스키마상 허용) outer join.
    "더보기"식 페이지네이션을 위해 offset을 받는다.
    """
    result = await session.execute(
        select(MatchLog, BusinessPlan.title)
        .join(BusinessPlan, MatchLog.business_plan_id == BusinessPlan.id, isouter=True)
        .where(MatchLog.user_id == user_id)
        .order_by(MatchLog.created_at.desc(), MatchLog.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_owned_by_user(
    session: AsyncSession, match_log_id: int, user_id: int
) -> tuple[MatchLog, str | None] | None:
    """유저 소유의 매칭 로그 한 건을 (로그, 사업계획서 제목)으로 반환한다.

    없거나 남의 로그면 None — 호출부가 존재 여부를 노출하지 않고 404로 답한다.
    """
    result = await session.execute(
        select(MatchLog, BusinessPlan.title)
        .join(BusinessPlan, MatchLog.business_plan_id == BusinessPlan.id, isouter=True)
        .where(MatchLog.id == match_log_id, MatchLog.user_id == user_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    return (row[0], row[1])

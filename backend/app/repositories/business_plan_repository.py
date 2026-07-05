"""
repositories/business_plan_repository.py

NRM-001: business_plan 테이블 조회/저장 로직.
서비스 레이어(services/business_plan_service.py)에서 이 함수들을 호출해서
DB 접근 없이 오케스트레이션 로직만 짤 수 있도록 분리함.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_plan import BusinessPlan


class BusinessPlanNotFoundError(Exception):
    """business_plan_id에 해당하는 레코드가 없을 때"""

    def __init__(self, business_plan_id: int):
        self.business_plan_id = business_plan_id
        super().__init__(f"BusinessPlan {business_plan_id} not found")


async def get_by_id(session: AsyncSession, business_plan_id: int) -> BusinessPlan | None:
    """business_plan_id로 레코드 조회. 없으면 None."""
    return await session.get(BusinessPlan, business_plan_id)


async def get_raw_text(session: AsyncSession, business_plan_id: int) -> str | None:
    """
    정규화 대상 원문(raw_text) 조회.
    - 레코드가 아예 없으면 BusinessPlanNotFoundError
    - 레코드는 있는데 raw_text가 비어있으면 None 반환 (호출 쪽에서 별도 처리)
    """
    plan = await get_by_id(session, business_plan_id)
    if plan is None:
        raise BusinessPlanNotFoundError(business_plan_id)
    return plan.raw_text


async def save_normalization_result(
    session: AsyncSession,
    business_plan_id: int,
    normalized_json: dict,
    analyzed_at: datetime | None = None,
) -> BusinessPlan:
    """
    정규화 결과를 analysis_json / analyzed_at에 저장.
    재정규화 정책(덮어쓰기 vs 차단)이 아직 미확정이라, 지금은 단순 덮어쓰기로 구현.
    TODO: 정책 확정되면 이미 analyzed_at이 있을 때의 분기 처리 추가 예정.
    """
    plan = await get_by_id(session, business_plan_id)
    if plan is None:
        raise BusinessPlanNotFoundError(business_plan_id)

    resolved_at = analyzed_at or datetime.now(timezone.utc)
    if resolved_at.tzinfo is not None:
        # analyzed_at 컬럼이 TIMESTAMP WITHOUT TIME ZONE이라 asyncpg가
        # tz-aware datetime을 그대로 넘기면 DataError를 던짐. UTC로 맞춰서 벗겨낸다.
        resolved_at = resolved_at.astimezone(timezone.utc).replace(tzinfo=None)

    plan.analysis_json = normalized_json
    plan.analyzed_at = resolved_at

    await session.commit()
    await session.refresh(plan)
    return plan


async def list_recent(session: AsyncSession, limit: int = 20) -> list[BusinessPlan]:
    """최근 등록된 사업계획서 목록 (디버깅/관리용, 필요시 사용)"""
    result = await session.execute(
        select(BusinessPlan).order_by(BusinessPlan.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
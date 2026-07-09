"""
Repository helpers for business_plan rows.

This module is shared by the text extraction flow, which stores raw_text, and
the normalization flow, which reads raw_text and stores analysis_json.
"""

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_plan import BusinessPlan


class BusinessPlanNotFoundError(Exception):
    """Raised when no business_plan row exists for the requested id."""

    def __init__(self, business_plan_id: int):
        self.business_plan_id = business_plan_id
        super().__init__(f"BusinessPlan {business_plan_id} not found")


async def get_by_id(session: AsyncSession, business_plan_id: int) -> BusinessPlan | None:
    """Return a business_plan row by id, or None when it does not exist."""
    return await session.get(BusinessPlan, business_plan_id)


async def get_raw_text(session: AsyncSession, business_plan_id: int) -> str | None:
    """
    Return raw_text for normalization.

    Missing rows raise BusinessPlanNotFoundError. Existing rows with empty
    raw_text return None so the service layer can decide how to fail.
    """
    plan = await get_by_id(session, business_plan_id)
    if plan is None:
        raise BusinessPlanNotFoundError(business_plan_id)
    return plan.raw_text


async def save_raw_text(
    session: AsyncSession, business_plan_id: int, raw_text: str, file_type: str
) -> None:
    """Persist extracted source text on an existing business_plan row."""
    result = await session.execute(
        update(BusinessPlan)
        .where(BusinessPlan.id == business_plan_id)
        .values(raw_text=raw_text, file_type=file_type)
    )
    if result.rowcount == 0:
        raise BusinessPlanNotFoundError(business_plan_id)


async def save_normalization_result(
    session: AsyncSession,
    business_plan_id: int,
    normalized_json: dict,
    analyzed_at: datetime | None = None,
) -> BusinessPlan:
    """Persist normalized analysis_json and analyzed_at."""
    plan = await get_by_id(session, business_plan_id)
    if plan is None:
        raise BusinessPlanNotFoundError(business_plan_id)

    resolved_at = analyzed_at or datetime.now(timezone.utc)
    if resolved_at.tzinfo is not None:
        resolved_at = resolved_at.astimezone(timezone.utc).replace(tzinfo=None)

    plan.analysis_json = normalized_json
    plan.analyzed_at = resolved_at

    await session.commit()
    await session.refresh(plan)
    return plan


async def list_recent(session: AsyncSession, limit: int = 20) -> list[BusinessPlan]:
    """Return recently created business plans for debugging/admin use."""
    result = await session.execute(
        select(BusinessPlan).order_by(BusinessPlan.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())

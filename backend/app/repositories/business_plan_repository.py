"""
Repository helpers for business_plan rows.

This module is shared by the text extraction flow, which stores raw_text, and
the normalization flow, which reads raw_text and stores analysis_json.
"""

from datetime import datetime, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_plan import BusinessPlan
from app.models.company import CompanyProfile
from app.schemas.business_plan import JobStatus


class BusinessPlanNotFoundError(Exception):
    """Raised when no business_plan row exists for the requested id."""

    def __init__(self, business_plan_id: int):
        self.business_plan_id = business_plan_id
        super().__init__(f"BusinessPlan {business_plan_id} not found")


async def create(
    session: AsyncSession,
    *,
    company_profile_id: int,
    title: str | None,
    file_url: str,
    file_type: str | None,
) -> BusinessPlan:
    """Insert a new business_plan row for an uploaded file.

    Flushes to populate the generated id but does not commit; the caller
    (service) owns the transaction boundary. uploaded_at is stored as naive
    UTC to match the column type.
    """
    plan = BusinessPlan(
        company_profile_id=company_profile_id,
        title=title,
        file_url=file_url,
        file_type=file_type,
        uploaded_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(plan)
    await session.flush()
    return plan


async def get_by_id(
    session: AsyncSession, business_plan_id: int
) -> BusinessPlan | None:
    """Return a business_plan row by id, or None when it does not exist."""
    return await session.get(BusinessPlan, business_plan_id)


async def get_owned_by_user(
    session: AsyncSession, business_plan_id: int, user_id: int
) -> BusinessPlan | None:
    """Return the business_plan only if it belongs to the user.

    Ownership goes business_plan -> company_profile -> user. Returns None when
    the plan does not exist OR belongs to someone else, so callers can answer
    404 either way without leaking whether another user's plan exists.
    """
    result = await session.execute(
        select(BusinessPlan)
        .join(CompanyProfile, BusinessPlan.company_profile_id == CompanyProfile.id)
        .where(
            BusinessPlan.id == business_plan_id,
            CompanyProfile.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_latest_by_company_profile(
    session: AsyncSession, company_profile_id: int
) -> BusinessPlan | None:
    """해당 기업 프로필의 가장 최근 업로드 business_plan을 반환한다."""
    result = await session.execute(
        select(BusinessPlan)
        .where(BusinessPlan.company_profile_id == company_profile_id)
        .order_by(BusinessPlan.uploaded_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


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


async def try_claim_analysis(
    session: AsyncSession, business_plan_id: int, *, stale_before: datetime
) -> bool:
    """분석 잡 실행권을 원자적으로 선점한다. 선점했으면 True.

    같은 plan에 분석 시작 요청이 동시에(새로고침, StrictMode 이중 실행 등)
    들어와도 조건부 UPDATE 한 번이 DB 행 잠금으로 직렬화되어 하나만 성공한다.
    이미 processing인 행은 선점에 실패하고(멱등 — 호출자는 기존 상태를
    돌려주면 된다), 예외로 analysis_started_at이 stale_before보다 오래된
    processing은 잡 도중 서버가 죽어 박제된 것으로 보고 재선점을 허용한다.

    선점 결과가 다른 요청·워커에 즉시 보여야 하므로 여기서 commit한다.
    """
    result = await session.execute(
        update(BusinessPlan)
        .where(
            BusinessPlan.id == business_plan_id,
            or_(
                # NULL != 'processing'은 SQL에서 매칭되지 않으므로 NULL을 따로 허용
                BusinessPlan.analysis_status.is_(None),
                BusinessPlan.analysis_status != JobStatus.PROCESSING.value,
                BusinessPlan.analysis_started_at.is_(None),
                BusinessPlan.analysis_started_at < stale_before,
            ),
        )
        .values(
            analysis_status=JobStatus.PROCESSING.value,
            analysis_step=None,
            analysis_error=None,
            analysis_started_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    await session.commit()
    return result.rowcount == 1


async def set_analysis_step(
    session: AsyncSession, business_plan_id: int, step: str
) -> None:
    """processing 중 현재 단계를 갱신한다.

    폴링 GET이 요청마다 다른 세션으로 읽으므로 바로 commit해서 보이게 한다.
    """
    await session.execute(
        update(BusinessPlan)
        .where(BusinessPlan.id == business_plan_id)
        .values(analysis_step=step)
    )
    await session.commit()


async def finish_analysis(
    session: AsyncSession,
    business_plan_id: int,
    *,
    status: str,
    error_message: str | None = None,
) -> None:
    """분석 잡의 종료 상태(completed/failed)와 실패 사유를 기록한다."""
    await session.execute(
        update(BusinessPlan)
        .where(BusinessPlan.id == business_plan_id)
        .values(
            analysis_status=status,
            analysis_step=None,
            analysis_error=error_message,
        )
    )
    await session.commit()


async def list_recent(session: AsyncSession, limit: int = 20) -> list[BusinessPlan]:
    """Return recently created business plans for debugging/admin use."""
    result = await session.execute(
        select(BusinessPlan).order_by(BusinessPlan.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())

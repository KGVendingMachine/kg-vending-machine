from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.business_plan import JobStatus


class MatchLogCreateRequest(BaseModel):
    business_plan_id: int
    max_results: int = Field(default=10, ge=1, le=50)


class MatchLogResponse(BaseModel):
    id: int
    business_plan_id: int | None
    business_plan_title: str | None
    run_status: JobStatus | None
    created_at: datetime
    completed_at: datetime | None


class MatchResultResponse(BaseModel):
    id: int
    match_log_id: int
    notice_id: int
    notice_title: str | None = None
    total_score: Decimal | None
    eligibility_score: Decimal | None
    item_fit_score: Decimal | None
    business_fit_score: Decimal | None
    growth_score: Decimal | None
    bonus_score: Decimal | None
    eligibility_status: str | None
    recommendation_level: str | None
    summary_reason: str | None
    weakness: str | None
    strategy_suggestion: str | None
    result_json: dict | None = None
    created_at: datetime

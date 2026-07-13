from datetime import date, datetime
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


class MatchResultNoticeInfo(BaseModel):
    """결과 카드에 표시할 공고 요약."""

    id: int
    title: str | None
    organization_name: str | None
    category_name: str | None
    status: str | None
    application_end_date: date | None
    amount_label: str | None
    source_url: str | None
    apply_url: str | None


class MatchResultResponse(BaseModel):
    id: int
    match_log_id: int
    notice_id: int
    notice_title: str | None = None
    notice: MatchResultNoticeInfo | None = None
    """결과 페이지 카드 표시용 공고 요약. 리스트 조회에서만 채워진다."""
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
    is_bookmarked: bool = False
    """이 공고가 (현재 유저·이 실행의 사업계획서 기준) 담겨 있는지. 별표 채움 표시용."""
    bookmark_id: int | None = None
    """담겨 있으면 그 북마크 id(별표 해제 DELETE 에 사용). 아니면 None."""
    created_at: datetime

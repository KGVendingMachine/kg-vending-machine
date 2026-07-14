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


class SecondaryFilteringReasonLog(BaseModel):
    """2차 필터링 LLM 판정에서 요건 문장 하나가 어떻게 판정됐는지
    (secondary_filtering_judge_service.CriterionJudgment)."""

    criterion: str
    status: str
    """"충족" / "미충족" / "정보부족" 중 하나."""
    evidence: str | None
    is_exclusion: bool
    """True면 제외요건("~에 해당하지 않음"으로 재구성된 문장) 판정이다."""


class SecondaryFilteringNoticeLog(BaseModel):
    """2차 필터링에서 공고 하나가 어떻게 처리됐는지."""

    notice_id: int
    title: str | None
    embedded: bool
    """임베딩·유사도 검색에 실제로 쓰였는지. False면 total_score의 2차 필터링
    구성요소는 중립값(50.0)이다."""
    similarity_score: float | None = None
    """임베딩 유사도 점수(35~100) — LLM 판정 대상을 고르는 데만 쓰인 값이라
    secondary_filter_score와 다를 수 있다. 이 필드가 없던 구버전 match_log는
    기본값 None으로 채워진다."""
    llm_judged: bool = False
    """유사도 상위 K건에 들어 secondary_filtering_judge_service.judge_notice가
    실제로 판정을 수행했는지. False면 secondary_filter_score는
    similarity_score와 같다(또는 둘 다 없음)."""
    excluded: bool = False
    """제외요건이 확정돼 secondary_filter_score가 낮은 값으로 캡됐는지."""
    reasons: list[SecondaryFilteringReasonLog] = Field(default_factory=list)
    """llm_judged가 True일 때만 값이 있다 — 요건 문장별 판정 근거."""
    secondary_filter_score: float | None
    """total_score에 실제로 반영된 최종값. llm_judged가 True면 LLM 판정
    점수, 아니면 similarity_score와 동일(또는 둘 다 임베딩 실패로 없음)."""
    skip_reason: str | None
    """embedded가 False일 때만 값이 있다. "no_text" 또는 "embedding_failed"."""


class SecondaryFilteringScoreStats(BaseModel):
    min: float
    max: float
    avg: float


class SecondaryFilteringLogResponse(BaseModel):
    """GET /match-logs/{id}/secondary-filtering.

    matching_service._build_secondary_filtering_log가 만들어 match_log.
    secondary_filtering_log(JSONB)에 저장한 값을 그대로 반환한다.
    """

    match_log_id: int
    plan_embedded: bool
    plan_skip_reason: str | None
    candidate_count: int
    embedded_count: int
    judged_count: int = 0
    """유사도 상위 K건 중 실제로 LLM 판정까지 수행된 공고 수. 이 필드가
    없던 구버전 match_log는 기본값 0으로 채워진다."""
    skipped_count: int
    score_stats: SecondaryFilteringScoreStats | None
    notices: list[SecondaryFilteringNoticeLog]


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

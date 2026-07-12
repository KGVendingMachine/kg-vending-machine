"""
schemas/match_log.py

매칭 실행 로그 API 스키마.
POST /match-logs        -> 매칭 실행(로그 생성)
GET  /match-logs        -> 내 매칭 로그 리스트 (분석 페이지의 과거 기록)
GET  /match-logs/{id}   -> 단건 조회 (결과 페이지 헤더용)
"""

from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.business_plan import JobStatus


class MatchLogCreateRequest(BaseModel):
    business_plan_id: int
    """분석(정규화)이 완료된 사업계획서 id."""


class MatchLogResponse(BaseModel):
    """match_log 한 행 + 어떤 파일로 돌린 매칭인지 보여줄 사업계획서 제목."""

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
    """GET /match-logs/{id}/results 항목. match_result 한 행 + 공고 요약.

    점수 5종의 만점은 지원자격 30 / 아이템적합 25 / 사업화 20 / 성장성 15 /
    가점 10 (합계 100). 축별 근거는 result_json.axes에 있다.
    """

    id: int
    notice: MatchResultNoticeInfo
    total_score: float | None
    eligibility_score: float | None
    item_fit_score: float | None
    business_fit_score: float | None
    growth_score: float | None
    bonus_score: float | None
    eligibility_status: str | None
    """지원가능/조건부가능/지원불가/확인필요"""
    recommendation_level: str | None
    """강력추천/추천/보통/비추천"""
    summary_reason: str | None
    weakness: str | None
    strategy_suggestion: str | None
    result_json: dict | None

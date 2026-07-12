"""
schemas/match_log.py

매칭 실행 로그 API 스키마.
POST /match-logs        -> 매칭 실행(로그 생성)
GET  /match-logs        -> 내 매칭 로그 리스트 (분석 페이지의 과거 기록)
GET  /match-logs/{id}   -> 단건 조회 (결과 페이지 헤더용)
"""

from datetime import datetime

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

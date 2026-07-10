"""
schemas/business_plan_analysis.py

사업계획서 분석(OCR + 정규화) API 스키마.
POST /business-plans/{id}/analysis            -> 분석 작업 시작 (202 Accepted)
GET  /business-plans/{id}/analysis/{job_id}   -> 상태/결과 조회

기존 정규화(/normalizations)는 raw_text가 이미 DB에 있다고 가정하지만, 이 분석은
업로드 직후 raw_text가 비어있는 상태에서 OCR부터 시작하는 전체 흐름이다. 진행
상태는 인메모리로 추적하고, 결과(analysis_json)는 business_plan 행에 저장된다.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.schemas.business_plan import JobStatus, NormalizedBusinessPlanSchema


class AnalysisStep(str, Enum):
    """PROCESSING 중 현재 어느 단계인지 (프론트 진행 표시용)."""

    EXTRACTING = "extracting"  # OCR로 원문 추출 중
    NORMALIZING = "normalizing"  # LLM 정규화 중


class AnalysisJobAccepted(BaseModel):
    """POST /business-plans/{id}/analysis 응답 (202 Accepted)."""

    business_plan_id: int
    job_id: str
    status: JobStatus = JobStatus.PENDING


class AnalysisStatusResponse(BaseModel):
    """GET /business-plans/{id}/analysis/{job_id} 응답."""

    business_plan_id: int
    job_id: str
    status: JobStatus
    step: AnalysisStep | None = None
    """PROCESSING일 때 현재 단계. 그 외 상태에서는 None."""
    analysis_json: NormalizedBusinessPlanSchema | None = None
    """status == completed 일 때 정규화 결과."""
    analyzed_at: datetime | None = None
    error_message: str | None = None
    """status == failed 일 때 실패 사유 (OCR 실패, 원문 없음, LLM 재시도 초과 등)."""

"""
schemas/business_plan_analysis.py

사업계획서 분석(OCR + 정규화) API 스키마.
POST /business-plans/{id}/analysis   -> 분석 작업 시작 (202 Accepted)
GET  /business-plans/{id}/analysis   -> 상태/결과 조회 (폴링)

기존 정규화(/normalizations)는 raw_text가 이미 DB에 있다고 가정하지만, 이 분석은
업로드 직후 raw_text가 비어있는 상태에서 OCR부터 시작하는 전체 흐름이다. 진행
상태·결과 모두 business_plan 행(analysis_* 컬럼)에 저장되므로 별도 job_id 없이
plan id만으로 조회한다 — 창을 닫았다 다시 들어와도 상태를 복구할 수 있다.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.schemas.business_plan import JobStatus, NormalizedBusinessPlanSchema


class AnalysisStep(str, Enum):
    """PROCESSING 중 현재 어느 단계인지 (프론트 진행 표시용)."""

    EXTRACTING = "extracting"  # OCR로 원문 추출 중
    NORMALIZING = "normalizing"  # LLM 정규화 중


class AnalysisStatusResponse(BaseModel):
    """POST/GET /business-plans/{id}/analysis 공통 응답.

    business_plan 행의 analysis_* 컬럼을 그대로 비춘 것. POST도 (선점 성공
    여부와 무관하게) 시작 직후의 현재 상태를 같은 형태로 돌려준다.
    """

    business_plan_id: int
    status: JobStatus | None = None
    """분석 잡 상태. None이면 아직 분석을 시작한 적이 없는 plan."""
    step: AnalysisStep | None = None
    """PROCESSING일 때 현재 단계. 그 외 상태에서는 None."""
    analysis_json: NormalizedBusinessPlanSchema | None = None
    """status == completed 일 때 정규화 결과."""
    analyzed_at: datetime | None = None
    error_message: str | None = None
    """status == failed 일 때 실패 사유 (OCR 실패, 원문 없음, LLM 재시도 초과 등)."""

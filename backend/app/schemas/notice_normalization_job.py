"""
schemas/notice_normalization_job.py

공고 정규화 트리거 API 스키마.
POST /internal/notices/{notice_id}/normalize          -> 정규화 작업 시작 (202 Accepted)
GET  /internal/notices/{notice_id}/normalize/{job_id} -> 작업 상태/결과 조회
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.schemas.business_plan import ValidationResult
from app.schemas.notice_normalization import NormalizedNoticeSchema


class NoticeNormalizationJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class NoticeNormalizationJobAccepted(BaseModel):
    """POST /internal/notices/{notice_id}/normalize 응답 (202 Accepted)"""

    notice_id: int
    job_id: str
    status: NoticeNormalizationJobStatus = NoticeNormalizationJobStatus.PENDING


class NoticeNormalizationJobStatusResponse(BaseModel):
    """GET /internal/notices/{notice_id}/normalize/{job_id} 응답"""

    notice_id: int
    job_id: str
    status: NoticeNormalizationJobStatus
    normalized_json: NormalizedNoticeSchema | None = None
    validation_result: ValidationResult | None = None
    normalized_at: datetime | None = None
    error_message: str | None = None
    """status == failed일 때 실패 사유 (예: 정규화 원문 없음, LLM 오류)"""

"""
schemas/notice_normalization_job.py

공고 정규화 트리거 API 스키마.
POST /internal/notices/{notice_id}/normalize          -> 정규화 작업 시작 (202 Accepted)
GET  /internal/notices/{notice_id}/normalize/{job_id} -> 작업 상태/결과 조회
POST /internal/notices/normalize/batch                -> 여러 공고 정규화 작업 일괄 시작 (202 Accepted)
GET  /internal/notices/normalize/batch/status         -> 배치 상태 일괄 조회
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

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


class NoticeNormalizationBatchTriggerRequest(BaseModel):
    # OCR 배치(notice_ocr.py)와 동일하게 30건으로 제한한다 — 실수로 대량
    # 요청이 들어와 OpenAI 비용이 한 번에 크게 나가는 것을 막기 위함.
    notice_ids: list[int] = Field(min_length=1, max_length=30)


class NoticeNormalizationBatchJobItem(BaseModel):
    notice_id: int
    job_id: str
    status: NoticeNormalizationJobStatus


class NoticeNormalizationBatchTriggerResponse(BaseModel):
    items: list[NoticeNormalizationBatchJobItem]


class NoticeNormalizationBatchStatusResponse(BaseModel):
    items: list[NoticeNormalizationJobStatusResponse]


class NoticeNormalizationResultResponse(BaseModel):
    """GET /internal/notices/{notice_id}/normalization 응답.

    job 상태 조회(_JOBS)와 달리 DB(Notice.normalized_json 등)에 영속화된
    결과를 읽는다 — _JOBS는 인메모리라 서버 재시작·다른 워커에서는 job_id로
    결과를 볼 수 없지만, 이 API는 언제든 notice_id만으로 조회할 수 있다.
    """

    notice_id: int
    normalization_status: str | None = None
    """completed/failed, 아직 정규화를 시도한 적 없으면 null"""
    normalized_json: NormalizedNoticeSchema | None = None
    normalization_error: str | None = None
    normalized_at: datetime | None = None

"""
schemas/notice_embedding.py

공고 첨부파일 임베딩(2차 필터링) 트리거 API 스키마.
POST /internal/notices/{notice_id}/embed             -> 임베딩 작업 시작 (202 Accepted)
GET  /internal/notices/{notice_id}/embed/{job_id}    -> 작업 상태/결과 조회
POST /internal/notices/embed/batch                   -> 여러 공고 임베딩 작업 일괄 시작 (202 Accepted)

notice_ocr.py의 스키마 구조를 그대로 따른다.
"""

from enum import Enum

from pydantic import BaseModel, Field


class NoticeEmbeddingJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_TEXT = "no_text"
    """공고에 임베딩할 원문이 없음(첨부파일 없음 또는 OCR 텍스트 없음) —
    실패가 아니라 정상적인 결과 상태. notice_ocr.py의 NO_ATTACHMENT/
    UNSUPPORTED_FORMAT과 같은 성격으로, 이 공고는 2차 필터링(유사도 검색)
    대상에서 제외된다."""


class NoticeEmbeddingJobAccepted(BaseModel):
    job_id: str
    status: NoticeEmbeddingJobStatus = NoticeEmbeddingJobStatus.PENDING


class NoticeEmbeddingJobStatusResponse(BaseModel):
    job_id: str
    notice_id: int
    status: NoticeEmbeddingJobStatus
    chunk_count: int | None = None
    error_message: str | None = None


class NoticeEmbeddingBatchTriggerRequest(BaseModel):
    # notice_ocr.py의 배치 상한(30건)과 동일한 이유 — 실수로 대량 요청이 들어가
    # OpenAI 임베딩 비용이 한 번에 크게 나가는 것을 막는다.
    notice_ids: list[int] = Field(min_length=1, max_length=30)


class NoticeEmbeddingBatchJobItem(BaseModel):
    notice_id: int
    job_id: str
    status: NoticeEmbeddingJobStatus


class NoticeEmbeddingBatchTriggerResponse(BaseModel):
    items: list[NoticeEmbeddingBatchJobItem]


class NoticeEmbeddingBatchStatusResponse(BaseModel):
    items: list[NoticeEmbeddingJobStatusResponse]

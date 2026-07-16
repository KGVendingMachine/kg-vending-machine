"""
schemas/notice_embedding_backlog.py

공고 임베딩(2차 필터링) 밀린 건 수동 일괄 처리 API 스키마.
POST /internal/notices/embed/backlog             -> 대상 전체 조회 + 일괄 트리거 (202 Accepted)
GET  /internal/notices/embed/backlog/{job_id}   -> 진행 상태 조회
"""

from enum import Enum

from pydantic import BaseModel, Field


class EmbeddingBacklogJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EmbeddingBacklogTriggerRequest(BaseModel):
    # 무제한으로 받으면 배치 하나가 몇 시간씩 걸릴 수 있어 상한을 둔다.
    limit: int = Field(default=5000, ge=1, le=20000)


class EmbeddingBacklogJobAccepted(BaseModel):
    job_id: str
    status: EmbeddingBacklogJobStatus = EmbeddingBacklogJobStatus.PENDING
    total: int


class EmbeddingBacklogJobStatusResponse(BaseModel):
    job_id: str
    status: EmbeddingBacklogJobStatus
    total: int
    processed: int = 0
    error_message: str | None = None

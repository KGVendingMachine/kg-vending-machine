"""
schemas/notice_normalization_backlog.py

공고 정규화 밀린 건 수동 일괄 처리 API 스키마.
POST /internal/notices/normalize/backlog             -> 대상 전체 조회 + 일괄 트리거 (202 Accepted)
GET  /internal/notices/normalize/backlog/{job_id}    -> 진행 상태 조회
"""

from enum import Enum

from pydantic import BaseModel, Field


class NormalizationBacklogJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class NormalizationBacklogTriggerRequest(BaseModel):
    # 무제한으로 받으면 배치 하나가 몇 시간씩 걸릴 수 있어 상한을 둔다.
    limit: int = Field(default=5000, ge=1, le=20000)


class NormalizationBacklogJobAccepted(BaseModel):
    job_id: str
    status: NormalizationBacklogJobStatus = NormalizationBacklogJobStatus.PENDING
    total: int


class NormalizationBacklogJobStatusResponse(BaseModel):
    job_id: str
    status: NormalizationBacklogJobStatus
    total: int
    processed: int = 0
    error_message: str | None = None

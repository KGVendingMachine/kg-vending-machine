"""
schemas/notice_collection.py

공고 수집(기업마당/K-Startup) 트리거 API 스키마.
POST /internal/notices/collect              -> 수집 작업 시작 (202 Accepted)
GET  /internal/notices/collect/{job_id}      -> 작업 상태/결과 조회
"""

from enum import Enum

from pydantic import BaseModel, Field


class CollectionJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceCollectionResult(BaseModel):
    """CollectionResult(app/services/notice_collection_service.py)를 그대로 옮긴 응답용 모델."""

    saved_count: int
    failed_count: int
    failed_ids: list[str] = Field(default_factory=list)


class CollectionJobAccepted(BaseModel):
    """POST /internal/notices/collect 응답 (202 Accepted)"""

    job_id: str
    status: CollectionJobStatus = CollectionJobStatus.PENDING


class CollectionJobStatusResponse(BaseModel):
    """GET /internal/notices/collect/{job_id} 응답"""

    job_id: str
    status: CollectionJobStatus
    current_phase: str | None = None
    """진행 중인 단계 (예: "기업마당 수집 중", "K-Startup 수집 중")"""
    bizinfo_result: SourceCollectionResult | None = None
    kstartup_result: SourceCollectionResult | None = None
    error_message: str | None = None

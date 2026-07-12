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


class CategoryBackfillResult(BaseModel):
    """POST /internal/notices/backfill-category 응답"""

    checked: int
    """category_id가 비어있어 검사한 공고 수"""
    updated: int
    """실제로 category_id를 채운 공고 수"""


class StatusRefreshResult(BaseModel):
    """POST /internal/notices/refresh-status 응답"""

    checked: int
    """마감 처리되지 않아 검사한 공고 수"""
    updated: int
    """실제로 status가 바뀐 공고 수 (주로 마감일 경과로 인한 마감 처리)"""


class BizinfoRegionBackfillResult(BaseModel):
    """POST /internal/notices/backfill-bizinfo-region 응답"""

    checked: int
    """검사한 기업마당 공고 수"""
    updated: int
    """실제로 전국(region_code=ALL)이 추가된 공고 수"""


class RegionCodeBackfillResult(BaseModel):
    """POST /internal/notices/backfill-region-codes 응답"""

    checked: int
    """검사한 공고 수 (기업마당+K-Startup)"""
    updated: int
    """실제로 지역 코드가 재계산돼 바뀐 공고 수"""


class NoticeRecollectionResult(BaseModel):
    """POST /internal/notices/{notice_id}/recollect 응답"""

    notice_id: int
    message: str = "재수집이 완료되었습니다."


class CollectionStatsResponse(BaseModel):
    """GET /internal/notices/stats 응답"""

    by_source: dict[str, int]
    """출처(기업마당/K-Startup)별 저장된 공고 수"""
    by_category: dict[str, int]
    """kg밴딩머신용카테고리별 공고 수 (미분류 포함)"""
    by_status: dict[str, int]
    """모집중/마감/예정/확인필요별 공고 수"""
    ocr_pending_count: int
    """OCR 대상 포맷(PDF/HWP/HWPX) 첨부파일은 있지만 아직 하나도 OCR되지 않은 공고 수"""

"""
schemas/notice_ocr.py

공고 첨부파일 OCR 트리거 API 스키마.
POST /internal/notices/{notice_id}/ocr             -> OCR 작업 시작 (202 Accepted)
GET  /internal/notices/{notice_id}/ocr/{job_id}     -> 작업 상태/결과 조회
"""

from enum import Enum

from pydantic import BaseModel


class NoticeOcrJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ATTACHMENT = "no_attachment"
    """공고에 OCR 가능한 문서(PDF/HWP/HWPX) 첨부파일이 없음 — 실패가 아니라
    정상적인 결과 상태. 프론트는 이 경우 notice.source_url로 안내한다."""


class NoticeOcrJobAccepted(BaseModel):
    job_id: str
    status: NoticeOcrJobStatus = NoticeOcrJobStatus.PENDING


class NoticeOcrJobStatusResponse(BaseModel):
    job_id: str
    notice_id: int
    status: NoticeOcrJobStatus
    attachment_id: int | None = None
    file_name: str | None = None
    char_count: int | None = None
    error_message: str | None = None

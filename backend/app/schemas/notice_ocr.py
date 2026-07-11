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
    """공고에 첨부파일이 아예 없음 — 실패가 아니라 정상적인 결과 상태.
    프론트는 이 경우 notice.source_url로 안내한다."""
    UNSUPPORTED_FORMAT = "unsupported_format"
    """첨부파일은 있지만 전부 OCR 미지원 포맷(PDF/HWP/HWPX 아님, 예:
    ZIP/XLSX/이미지)임 — 실패가 아니라 정상적인 결과 상태. NO_ATTACHMENT와
    분리한 이유(2026-07-11, AI 팀 요청): AI 쪽에서 "원문이 전혀 없는 공고"와
    "원문은 있는데 우리가 못 여는 형식인 공고"를 구분해서 처리하고 싶어함.
    프론트 처리는 NO_ATTACHMENT와 동일(notice.source_url 안내)."""


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

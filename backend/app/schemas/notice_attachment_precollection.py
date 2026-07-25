"""
schemas/notice_attachment_precollection.py

공고 첨부파일 사전 OCR 트리거 API 스키마.
POST /internal/notices/attachment-ocr/precollect -> 사전 OCR 대상 조회 + 일괄 시작 (202 Accepted)
"""

from pydantic import BaseModel, Field

from app.schemas.notice_ocr import NoticeOcrBatchJobItem


class NoticeAttachmentPrecollectRequest(BaseModel):
    # NoticeOcrBatchTriggerRequest(30건 상한)를 여러 번 나눠 호출하므로 여기는
    # 더 크게 받되, 한 번의 호출이 무한정 커지지 않도록 상한을 둔다.
    limit: int = Field(default=100, ge=1, le=1000)


class NoticeAttachmentPrecollectResponse(BaseModel):
    notice_ids: list[int]
    items: list[NoticeOcrBatchJobItem]

"""
schemas/notice.py

공고 조회 API 스키마.
GET /notices          -> 목록 (필터/페이지네이션)
GET /notices/{notice_id} -> 상세
"""

from datetime import date, datetime

from pydantic import BaseModel


class NoticeSummary(BaseModel):
    """목록용 요약 정보."""

    id: int
    source: str
    """공고 출처 (기업마당/K-Startup)"""
    title: str | None
    category: str | None
    status: str | None
    application_start_date: date | None
    application_end_date: date | None
    regions: list[str]


class NoticeListResponse(BaseModel):
    total: int
    items: list[NoticeSummary]


class NoticeAttachmentInfo(BaseModel):
    file_name: str | None
    file_url: str | None
    file_type: str | None


class NoticeDetail(BaseModel):
    """상세 조회용 전체 정보."""

    id: int
    source: str
    title: str | None
    category: str | None
    status: str | None
    is_actionable: bool | None
    application_start_date: date | None
    application_end_date: date | None
    source_url: str | None
    apply_url: str | None
    summary_text: str | None
    amount_label: str | None
    regions: list[str]
    target_types: list[str]
    attachments: list[NoticeAttachmentInfo]
    created_at: datetime
    updated_at: datetime

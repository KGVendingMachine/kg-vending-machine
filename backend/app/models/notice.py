from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Notice(Base):
    __tablename__ = "notice"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("notice_source.id"), nullable=False
    )
    """공고 출처 ID"""
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organization.id"))
    """주관 기관 ID"""
    external_id: Mapped[str | None] = mapped_column(String(100))
    """외부 사이트 원본 ID (pblancId 등)"""
    notice_group_key: Mapped[str | None] = mapped_column(String(100))
    """연장/수정/N차 묶음 키"""
    title: Mapped[str | None] = mapped_column(String(500))
    """공고명"""
    target_business_years_max: Mapped[int | None] = mapped_column(Integer)
    """업력 상한(년), NULL=제한없음"""
    application_start_date: Mapped[date | None] = mapped_column(Date)
    """신청시작일"""
    application_end_date: Mapped[date | None] = mapped_column(Date)
    """신청종료일"""
    status: Mapped[str | None] = mapped_column(String(20))
    """모집중/마감/예정"""
    is_actionable: Mapped[bool | None] = mapped_column(Boolean)
    """신청가능여부"""
    source_url: Mapped[str | None] = mapped_column(Text)
    """공고 상세 URL"""
    apply_url: Mapped[str | None] = mapped_column(Text)
    """신청 페이지 URL (구글폼 로그인 리다이렉트 등 500자 넘는 URL이 실제로 있어 Text로 둠)"""
    summary_text: Mapped[str | None] = mapped_column(Text)
    """요약내용"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class NoticeTargetType(Base):
    __tablename__ = "notice_target_type"
    __table_args__ = (UniqueConstraint("notice_id", "target_type"),)

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    """공고아이디"""
    target_type: Mapped[str] = mapped_column(String(255), nullable=False)
    """청소년/대학생/일반인/대학/기업/창업/소상공인 등"""


class NoticeRegion(Base):
    __tablename__ = "notice_region"
    __table_args__ = (UniqueConstraint("notice_id", "region_code"),)

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    region_code: Mapped[str] = mapped_column(String(20), nullable=False)
    """행정표준코드, 전국=ALL"""
    region_name: Mapped[str | None] = mapped_column(String(100))
    """서울/경기/전국 등"""


class NoticeChunk(Base):
    __tablename__ = "notice_chunk"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    """공고아이디"""
    chunk_type: Mapped[str | None] = mapped_column(String(30))
    """임베딩한 단락"""
    chunk_text: Mapped[str | None] = mapped_column(Text)
    """임베딩한 텍스트"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class NoticeAttachment(Base):
    __tablename__ = "notice_attachment"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255))
    file_url: Mapped[str | None] = mapped_column(String(500))
    file_type: Mapped[str | None] = mapped_column(String(20))
    """PDF/HWP/DOCX"""
    parsed_text: Mapped[str | None] = mapped_column(Text)
    """파일 추출 텍스트"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

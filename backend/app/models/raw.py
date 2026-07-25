from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KstartupRaw(Base):
    """k_start_up 원문: K-Startup API 원본 응답 저장"""

    __tablename__ = "kstartup_raw"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    """k_startup ID"""
    field: Mapped[str | None] = mapped_column(Text)
    """json 원문"""
    notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    """공고 ID"""


class BizinfoRaw(Base):
    """기업마당 원문: 기업마당 API 원본 응답 저장"""

    __tablename__ = "bizinfo_raw"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    """기업마당ID"""
    field: Mapped[str | None] = mapped_column(Text)
    """json 원문"""
    notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    """공고 ID"""


class RefinedColumn(Base):
    """정제된컬럼: 원문에서 정제한 필드 저장"""

    __tablename__ = "refined_column"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    """ID"""
    field: Mapped[str | None] = mapped_column(Text)
    """json 원문"""
    notice_id: Mapped[int] = mapped_column(
        ForeignKey("notice.id", ondelete="CASCADE"), nullable=False
    )
    """공고 ID. 원본 공고가 지워지면 그 공고에서 정제한 파생 데이터도
    의미가 없어지므로 ON DELETE CASCADE로 자동 정리한다(notice_chunk와
    동일한 이유 — delete_notice()에 별도 삭제 코드를 추가할 필요 없음)."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KstartupRaw(Base):
    """k_start_up 원문: K-Startup API 원본 응답 저장"""

    __tablename__ = "kstartup_raw"

    key: Mapped[str] = mapped_column("Key", String(255), primary_key=True)
    """k_startup ID"""
    field: Mapped[str | None] = mapped_column("Field", String(255))
    """json 원문"""
    notice_id: Mapped[int] = mapped_column(
        "id", ForeignKey("notice.id"), nullable=False
    )
    """공고 ID"""


class BizinfoRaw(Base):
    """기업마당 원문: 기업마당 API 원본 응답 저장"""

    __tablename__ = "bizinfo_raw"

    key: Mapped[str] = mapped_column("Key", String(255), primary_key=True)
    """기업마당ID"""
    field: Mapped[str | None] = mapped_column("Field", String(255))
    """json 원문"""
    notice_id: Mapped[int] = mapped_column(
        "id", ForeignKey("notice.id"), nullable=False
    )
    """공고 ID"""


class RefinedColumn(Base):
    """정제된컬럼: 원문에서 정제한 필드 저장"""

    __tablename__ = "refined_column"

    key: Mapped[str] = mapped_column("Key", String(255), primary_key=True)
    """ID"""
    field: Mapped[str | None] = mapped_column("Field", String(255))
    """json 원문"""
    notice_id: Mapped[int] = mapped_column(
        "id", ForeignKey("notice.id"), nullable=False
    )
    """공고 ID"""

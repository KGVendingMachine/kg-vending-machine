from datetime import datetime

from sqlalchemy import DateTime, Identity, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NoticeSource(Base):
    __tablename__ = "notice_source"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    """기업마당/K-Startup 등"""
    base_url: Mapped[str | None] = mapped_column(String(255))
    """기본URL"""
    collect_type: Mapped[str | None] = mapped_column(String(30))
    """API/CRAWL"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

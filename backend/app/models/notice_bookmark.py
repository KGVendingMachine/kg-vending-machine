from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Identity, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NoticeBookmark(Base):
    __tablename__ = "notice_bookmark"
    __table_args__ = (
        UniqueConstraint("user_id", "notice_id", name="uq_notice_bookmark_user_notice"),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    """사용자아이디"""
    notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    """공고아이디"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

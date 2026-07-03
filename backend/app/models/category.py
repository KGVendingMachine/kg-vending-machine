import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Identity, String
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CategoryName(str, enum.Enum):
    """kg밴딩머신용카테고리.name 허용값"""

    FUND = "자금"
    TECH = "기술"
    MANPOWER = "인력"
    EXPORT = "수출"
    SALES = "판로"
    STARTUP = "창업"
    MANAGEMENT = "경영"
    COMMERCIALIZATION = "사업화"
    INCUBATION = "보육"
    EDUCATION = "교육"
    EVENT = "행사"


class KgCategory(Base):
    __tablename__ = "kg_category"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    name: Mapped[CategoryName] = mapped_column(
        SqlEnum(CategoryName, name="category_name"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class CategoryMapping(Base):
    __tablename__ = "category_mapping"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    raw_category: Mapped[str] = mapped_column(String(100), nullable=False)
    """K-Startup/기업마당 실제 카테고리"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("kg_category.id"), nullable=False
    )
    """kg밴딩머신용카테고리"""


class NoticeCategoryMap(Base):
    __tablename__ = "notice_category_map"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    """공고문아이디"""
    mapping_id: Mapped[int] = mapped_column(
        ForeignKey("category_mapping.id"), nullable=False
    )

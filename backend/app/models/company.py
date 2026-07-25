from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CompanyProfile(Base):
    __tablename__ = "company_profile"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    """사용자아이디"""
    company_name: Mapped[str | None] = mapped_column(String(255))
    """기업명 또는 예비창업팀명"""
    business_type: Mapped[str | None] = mapped_column(String(50))
    """사업자유형 개인사업자/법인사업자/예비창업자"""
    company_stage: Mapped[str | None] = mapped_column(String(50))
    """초기창업/중소기업 (예비창업자는 business_type이 표현, 소상공인은 company_size가 표현)"""
    region_code: Mapped[str | None] = mapped_column(String(20))
    """사업장 행정표준코드"""
    region_name: Mapped[str | None] = mapped_column(String(100))
    """지역명"""
    industry_code: Mapped[str | None] = mapped_column(String(20))
    """한국표준산업분류 코드"""
    founded_date: Mapped[date | None] = mapped_column(Date)
    """설립일"""
    business_years: Mapped[int | None] = mapped_column(Integer)
    """업력(년)"""
    employee_count: Mapped[int | None] = mapped_column(Integer)
    """상시근로자 수"""
    annual_revenue: Mapped[int | None] = mapped_column(BigInteger)
    """연매출 (원)"""
    representative_name: Mapped[str | None] = mapped_column(String(100))
    """대표자명"""
    business_registration_number: Mapped[str | None] = mapped_column(String(20))
    """사업자등록번호"""
    company_size: Mapped[str | None] = mapped_column(String(20))
    """기업 규모. 사용자 입력이 아니라 업종·매출에서 산출한 파생값
    (services/company_size.derive_company_size) — 현재는 중소기업/중견기업."""
    is_primary: Mapped[bool] = mapped_column(
        Boolean, server_default=false(), nullable=False
    )
    """대표 프로필 여부"""
    matching_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    """매칭 전 확인 모달에서 지역·기업형태가 맞다고 확인한 시각. null이면 미확인이라
    매칭 시작 전에 확인 모달을 띄운다."""
    file_url: Mapped[str | None] = mapped_column(String(500))
    """프로필 원본 파일 S3 경로"""
    spec_json: Mapped[dict | None] = mapped_column(JSONB)
    """특허/수출/투자/여성/청년 등 파생 플래그"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

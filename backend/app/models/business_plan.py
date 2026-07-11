from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Identity, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BusinessPlan(Base):
    __tablename__ = "business_plan"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    company_profile_id: Mapped[int] = mapped_column(
        ForeignKey("company_profile.id"), nullable=False
    )
    """기업프로필아이디"""
    title: Mapped[str | None] = mapped_column(String(255))
    """제목"""
    file_url: Mapped[str | None] = mapped_column(String(500))
    """S3파일URL"""
    file_type: Mapped[str | None] = mapped_column(String(20))
    """파일유형 PDF/HWP/HWPX/IMAGE (ocr.extract.file_type_for_suffix가 단일 소스)"""
    raw_text: Mapped[str | None] = mapped_column(Text)
    """원문"""
    analysis_json: Mapped[dict | None] = mapped_column(JSONB)
    """LLM 추출 결과 (분야/고객/문제/솔루션/기술/수익모델/팀역량 등)"""
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime)
    """분석일시"""
    analysis_status: Mapped[str | None] = mapped_column(String(20))
    """분석 잡 상태 processing/completed/failed. NULL이면 아직 시작 안 함"""
    analysis_step: Mapped[str | None] = mapped_column(String(20))
    """processing 중 현재 단계 extracting/normalizing (프론트 진행 표시용)"""
    analysis_error: Mapped[str | None] = mapped_column(Text)
    """failed일 때 실패 사유"""
    analysis_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    """분석 시작 시각. 잡 도중 서버가 죽어 processing이 박제된 행을
    일정 시간 뒤 재시작 가능으로 판정(stale 처리)하는 데 쓴다"""
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BusinessPlanChunk(Base):
    __tablename__ = "business_plan_chunk"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    business_plan_id: Mapped[int] = mapped_column(
        ForeignKey("business_plan.id"), nullable=False
    )
    """사업계획서아이디"""
    chunk_type: Mapped[str | None] = mapped_column(String(30))
    """청크유형 problem/solution/tech/market/team/revenue 등"""
    chunk_text: Mapped[str | None] = mapped_column(Text)
    """청크내용"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

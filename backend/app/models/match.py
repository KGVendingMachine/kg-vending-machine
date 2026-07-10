from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Identity, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MatchLog(Base):
    """매치 실행(추천 실행) 로그"""

    __tablename__ = "match_log"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    company_profile_id: Mapped[int] = mapped_column(
        ForeignKey("company_profile.id"), nullable=False
    )
    business_plan_id: Mapped[int | None] = mapped_column(ForeignKey("business_plan.id"))
    """NULL 가능"""
    run_status: Mapped[str | None] = mapped_column(String(20))
    """진행중/완료/실패"""
    query_text: Mapped[str | None] = mapped_column(Text)
    """생성된 검색 질의"""
    query_json: Mapped[dict | None] = mapped_column(JSONB)
    """구조화 질의"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class MatchResult(Base):
    __tablename__ = "match_result"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    recommendation_run_id: Mapped[int] = mapped_column(
        ForeignKey("match_log.id"), nullable=False
    )
    notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    total_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    """최종 적합도"""
    eligibility_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    """지원자격 적합도"""
    item_fit_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    """아이템/분야 적합도"""
    business_fit_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    """사업화 계획 적합도"""
    growth_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    """성장 가능성"""
    bonus_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    """가점 가능성"""
    eligibility_status: Mapped[str | None] = mapped_column(String(20))
    """지원가능/조건부가능/지원불가/확인필요"""
    recommendation_level: Mapped[str | None] = mapped_column(String(20))
    """강력추천/추천/보통/비추천"""
    summary_reason: Mapped[str | None] = mapped_column(Text)
    """추천 요약 근거"""
    weakness: Mapped[str | None] = mapped_column(Text)
    """보완 필요 부분"""
    strategy_suggestion: Mapped[str | None] = mapped_column(Text)
    """지원 시 강조 전략"""
    result_json: Mapped[dict | None] = mapped_column(JSONB)
    """LLM 평가 전체 원본"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class MatchReport(Base):
    __tablename__ = "match_report"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    match_run_id: Mapped[int] = mapped_column(
        ForeignKey("match_log.id"), nullable=False
    )
    """매치실행아이디"""
    content: Mapped[str | None] = mapped_column(Text)
    """내용"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

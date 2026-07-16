from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    secondary_filtering_log: Mapped[dict | None] = mapped_column(JSONB)
    """2차 필터링(공고 PDF·사업계획서 원문 임베딩 유사도) 실행 로그 — 후보 수,
    임베딩 성공/스킵 건수, 유사도 점수 분포, 공고별 세부 내역
    (docs/matching-pipeline.md 로깅 요구사항, secondary_filtering_service 참고)"""
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


class SecondaryFilteringJudgment(Base):
    """2차 필터링 LLM 판정 결과 캐시(2026-07-16, RAG 성능 개선 검토로 추가).

    같은 (사업계획서, 공고) 조합이면 임베딩처럼 판정도 재사용해 LLM 호출을
    줄인다. 다만 판정은 회사 프로필 값(_company_profile_text가 참조하는
    필드들)에도 의존해서 임베딩처럼 무조건 영구 캐싱하면 안 된다 —
    profile_fingerprint(그 필드들의 해시)를 키에 포함해, 사용자가 프로필을
    바꾸면 자동으로 캐시 미스가 나게 한다. 공고 재수집으로 normalized_json이
    바뀌는 경우까지는 무효화하지 않는다(드문 경우라 이번 범위에서는 TBD로
    남김 — secondary_filtering_judge_service 참고).
    """

    __tablename__ = "secondary_filtering_judgment"
    __table_args__ = (
        UniqueConstraint(
            "business_plan_id",
            "notice_id",
            "profile_fingerprint",
            name="uq_secondary_filtering_judgment_key",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    business_plan_id: Mapped[int] = mapped_column(
        ForeignKey("business_plan.id", ondelete="CASCADE"), nullable=False
    )
    notice_id: Mapped[int] = mapped_column(
        ForeignKey("notice.id", ondelete="CASCADE"), nullable=False
    )
    profile_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    """_company_profile_text가 참조하는 프로필 필드들의 해시(SHA256 앞 16자).
    프로필이 바뀌면 값이 달라져 캐시 미스가 난다."""
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fit_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    """criteria_fit(평가기준) 그룹 판정 평균*100. 판정 대상 없으면 NULL(R&D 전용)."""
    bonus_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    """bonus_fit(우대조건) 그룹 판정 평균*100. 의미는 fit_score와 동일."""
    item_fit_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    """item_fit(아이템 적합도) 그룹 판정 평균*100. 의미는 fit_score와 동일."""
    judgments: Mapped[list] = mapped_column(JSONB, nullable=False)
    """CriterionJudgment 목록(criterion/status/evidence/group)."""
    judged_at: Mapped[datetime] = mapped_column(
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

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Identity, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NoticeBookmark(Base):
    """공고 북마크.

    우리 서비스의 공고는 '특정 사업계획서로 매칭한 결과'로 등장하므로, 북마크
    하나는 (사용자, 공고) 가 아니라 **(사용자, 공고, 사업계획서)** 단위다. 같은
    공고라도 사업계획서가 다르면 추천 이유·점수가 달라 별개의 북마크로 본다.
    business_plan_id 는 담을 당시의 맥락을 얼려 두는 불변 스냅샷이라(계획서가
    지워져도 값을 유지) SET NULL 을 걸지 않는다. 추천 밖(공고 목록 브라우징)에서
    담은 경우 business_plan_id·match_result_id 가 NULL, source='browse'.
    """

    __tablename__ = "notice_bookmark"
    __table_args__ = (
        # (user, notice, plan) 단위 유일. business_plan_id 가 NULL(브라우징)인
        # 북마크도 공고당 한 번만 담기도록 NULL 을 같은 값으로 취급한다(PG15+).
        UniqueConstraint(
            "user_id",
            "notice_id",
            "business_plan_id",
            name="uq_bookmark_user_notice_plan",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    """사용자아이디"""
    notice_id: Mapped[int] = mapped_column(
        ForeignKey("notice.id", ondelete="CASCADE"), nullable=False
    )
    """공고아이디. 원본 공고가 지워지면 그 북마크도 의미가 없어지므로 CASCADE."""
    business_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_plan.id")
    )
    """추천 기반이 된 사업계획서. 담을 당시 맥락의 불변 스냅샷이자 최신성(stale)
    판정 기준. 브라우징으로 담았으면 NULL. 계획서가 지워져도 값을 유지해야
    하므로 SET NULL 을 걸지 않는다."""
    match_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("match_result.id", ondelete="SET NULL")
    )
    """담을 당시 그 추천 카드(점수·이유 원본). 재추천은 새 match_log 를 만들어
    이 행을 지우지 않으므로 영구 포인터로 유효하다. 회원탈퇴 등으로 결과가
    지워지는 예외에 대비해 SET NULL(정체성 컬럼이 아니라 유니크 제약과 무관)."""
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    """담은 경로 recommendation/browse"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

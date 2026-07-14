"""notice_bookmark 추천 컨텍스트 추가

공고 북마크를 (사용자, 공고) 에서 (사용자, 공고, 사업계획서) 단위로 확장한다.
- business_plan_id: 추천 기반 사업계획서(불변 스냅샷·stale 판정 기준). 브라우징이면 NULL.
- match_result_id: 담을 당시 추천 카드(점수·이유 원본). ON DELETE SET NULL.
- source: recommendation/browse
- notice_id FK 를 ON DELETE CASCADE 로 변경(공고 삭제 시 북마크도 정리).
- 유니크 제약을 (user, notice, business_plan) 로 교체(NULLS NOT DISTINCT).

Revision ID: 9f3c1a2b7d64
Revises: c5260495294c
Create Date: 2026-07-13 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f3c1a2b7d64"
down_revision: Union[str, Sequence[str], None] = "c5260495294c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. 컬럼 추가
    op.add_column(
        "notice_bookmark",
        sa.Column("business_plan_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "notice_bookmark",
        sa.Column("match_result_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "notice_bookmark",
        sa.Column("source", sa.String(length=20), nullable=True),
    )
    # 기존 행(있다면)은 추천 맥락 없이 담긴 것이므로 browse 로 채운 뒤 NOT NULL 확정.
    op.execute("UPDATE notice_bookmark SET source = 'browse' WHERE source IS NULL")
    op.alter_column("notice_bookmark", "source", nullable=False)

    # 2. 새 FK
    op.create_foreign_key(
        "notice_bookmark_business_plan_id_fkey",
        "notice_bookmark",
        "business_plan",
        ["business_plan_id"],
        ["id"],
    )
    op.create_foreign_key(
        "notice_bookmark_match_result_id_fkey",
        "notice_bookmark",
        "match_result",
        ["match_result_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. notice_id FK 를 ON DELETE CASCADE 로 교체
    op.drop_constraint(
        "notice_bookmark_notice_id_fkey", "notice_bookmark", type_="foreignkey"
    )
    op.create_foreign_key(
        "notice_bookmark_notice_id_fkey",
        "notice_bookmark",
        "notice",
        ["notice_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 4. 유니크 제약 교체: (user, notice) -> (user, notice, business_plan), NULLS NOT DISTINCT
    op.drop_constraint(
        "uq_notice_bookmark_user_notice", "notice_bookmark", type_="unique"
    )
    op.create_unique_constraint(
        "uq_bookmark_user_notice_plan",
        "notice_bookmark",
        ["user_id", "notice_id", "business_plan_id"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 4. 유니크 제약 원복
    op.drop_constraint(
        "uq_bookmark_user_notice_plan", "notice_bookmark", type_="unique"
    )
    op.create_unique_constraint(
        "uq_notice_bookmark_user_notice",
        "notice_bookmark",
        ["user_id", "notice_id"],
    )

    # 3. notice_id FK 원복(ondelete 제거)
    op.drop_constraint(
        "notice_bookmark_notice_id_fkey", "notice_bookmark", type_="foreignkey"
    )
    op.create_foreign_key(
        "notice_bookmark_notice_id_fkey",
        "notice_bookmark",
        "notice",
        ["notice_id"],
        ["id"],
    )

    # 2. 새 FK 제거
    op.drop_constraint(
        "notice_bookmark_match_result_id_fkey", "notice_bookmark", type_="foreignkey"
    )
    op.drop_constraint(
        "notice_bookmark_business_plan_id_fkey", "notice_bookmark", type_="foreignkey"
    )

    # 1. 컬럼 제거
    op.drop_column("notice_bookmark", "source")
    op.drop_column("notice_bookmark", "match_result_id")
    op.drop_column("notice_bookmark", "business_plan_id")

"""company_profile.matching_confirmed_at 컬럼 추가 (매칭 전 확인 플래그)

업로드 우선 온보딩(#142): 매칭 시작 전 확인 모달에서 지역·기업형태가 맞다고
확인한 시각. null이면 미확인이라 모달을 띄운다.

Revision ID: e91c4f27ab53
Revises: ae2a0877b620
Create Date: 2026-07-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e91c4f27ab53"
down_revision: Union[str, Sequence[str], None] = "ae2a0877b620"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "company_profile",
        sa.Column("matching_confirmed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("company_profile", "matching_confirmed_at")

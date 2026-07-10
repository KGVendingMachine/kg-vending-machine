"""add notice normalization columns

Revision ID: a9c4f2d1e8b6
Revises: 7deb161d8f0e
Create Date: 2026-07-10 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a9c4f2d1e8b6"
down_revision: Union[str, Sequence[str], None] = "7deb161d8f0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "notice",
        sa.Column(
            "normalized_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "notice",
        sa.Column("normalization_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "notice",
        sa.Column("normalization_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "notice",
        sa.Column("normalized_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("notice", "normalized_at")
    op.drop_column("notice", "normalization_error")
    op.drop_column("notice", "normalization_status")
    op.drop_column("notice", "normalized_json")

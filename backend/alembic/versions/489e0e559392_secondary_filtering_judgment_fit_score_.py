"""secondary_filtering_judgment_fit_score_bonus_score_추가

Revision ID: 489e0e559392
Revises: 4308fcbd06d3
Create Date: 2026-07-16 14:53:19.612230

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '489e0e559392'
down_revision: Union[str, Sequence[str], None] = '4308fcbd06d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "secondary_filtering_judgment",
        sa.Column("fit_score", sa.Numeric(precision=5, scale=2), nullable=True),
    )
    op.add_column(
        "secondary_filtering_judgment",
        sa.Column("bonus_score", sa.Numeric(precision=5, scale=2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("secondary_filtering_judgment", "bonus_score")
    op.drop_column("secondary_filtering_judgment", "fit_score")

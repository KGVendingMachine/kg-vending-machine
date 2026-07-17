"""secondary_filtering_judgment_item_fit_score_추가

Revision ID: ae2a0877b620
Revises: 489e0e559392
Create Date: 2026-07-16 20:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "ae2a0877b620"
down_revision: Union[str, Sequence[str], None] = "489e0e559392"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "secondary_filtering_judgment",
        sa.Column("item_fit_score", sa.Numeric(precision=5, scale=2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("secondary_filtering_judgment", "item_fit_score")

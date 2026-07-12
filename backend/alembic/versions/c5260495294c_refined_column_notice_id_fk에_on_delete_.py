"""refined_column notice_id FK에 ON DELETE CASCADE 추가

Revision ID: c5260495294c
Revises: c8c2c9bf4414
Create Date: 2026-07-12 15:24:47.872323

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5260495294c"
down_revision: Union[str, Sequence[str], None] = "c8c2c9bf4414"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("refined_column_id_fkey", "refined_column", type_="foreignkey")
    op.create_foreign_key(
        "refined_column_id_fkey",
        "refined_column",
        "notice",
        ["notice_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("refined_column_id_fkey", "refined_column", type_="foreignkey")
    op.create_foreign_key(
        "refined_column_id_fkey", "refined_column", "notice", ["notice_id"], ["id"]
    )

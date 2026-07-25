"""notice_chunk notice_id FK에 ON DELETE CASCADE 추가

Revision ID: c8c2c9bf4414
Revises: 31af39c03a7f
Create Date: 2026-07-11 22:08:48.998165

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8c2c9bf4414"
down_revision: Union[str, Sequence[str], None] = "31af39c03a7f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(
        "notice_chunk_notice_id_fkey", "notice_chunk", type_="foreignkey"
    )
    op.create_foreign_key(
        "notice_chunk_notice_id_fkey",
        "notice_chunk",
        "notice",
        ["notice_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "notice_chunk_notice_id_fkey", "notice_chunk", type_="foreignkey"
    )
    op.create_foreign_key(
        "notice_chunk_notice_id_fkey", "notice_chunk", "notice", ["notice_id"], ["id"]
    )

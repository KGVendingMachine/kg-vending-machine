"""add unique constraint notice source_id external_id

Revision ID: 6427b67264c8
Revises: 223608b4c37a
Create Date: 2026-07-03 17:29:21.146108

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6427b67264c8"
down_revision: Union[str, Sequence[str], None] = "223608b4c37a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(
        "uq_notice_source_id_external_id", "notice", ["source_id", "external_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_notice_source_id_external_id", "notice", type_="unique")

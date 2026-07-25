"""notice_source source_name 유니크 제약 추가

Revision ID: 9b809fce1a26
Revises: 6427b67264c8
Create Date: 2026-07-05 20:57:30.869436

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9b809fce1a26"
down_revision: Union[str, Sequence[str], None] = "6427b67264c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(
        "uq_notice_source_source_name", "notice_source", ["source_name"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_notice_source_source_name", "notice_source", type_="unique")

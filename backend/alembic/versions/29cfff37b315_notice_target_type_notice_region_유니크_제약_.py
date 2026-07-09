"""notice_target_type, notice_region 유니크 제약 추가

Revision ID: 29cfff37b315
Revises: 8d3fb3c72989
Create Date: 2026-07-06 17:21:54.852557

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "29cfff37b315"
down_revision: Union[str, Sequence[str], None] = "8d3fb3c72989"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(
        "uq_notice_region_notice_id_region_code",
        "notice_region",
        ["notice_id", "region_code"],
    )
    op.create_unique_constraint(
        "uq_notice_target_type_notice_id_target_type",
        "notice_target_type",
        ["notice_id", "target_type"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_notice_target_type_notice_id_target_type",
        "notice_target_type",
        type_="unique",
    )
    op.drop_constraint(
        "uq_notice_region_notice_id_region_code", "notice_region", type_="unique"
    )

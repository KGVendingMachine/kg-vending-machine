"""merge_business_years_and_dup_head

Revision ID: 6742607b62d0
Revises: b3d9f1c04e27, ec70d31b6582
Create Date: 2026-07-15 16:50:57.083524

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6742607b62d0'
down_revision: Union[str, Sequence[str], None] = ('b3d9f1c04e27', 'ec70d31b6582')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

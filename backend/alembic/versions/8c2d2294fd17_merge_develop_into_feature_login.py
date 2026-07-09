"""merge develop into feature/login

Revision ID: 8c2d2294fd17
Revises: 0756e6c105fe, 98707c1440ad
Create Date: 2026-07-09 10:58:32.648325

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c2d2294fd17'
down_revision: Union[str, Sequence[str], None] = ('0756e6c105fe', '98707c1440ad')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

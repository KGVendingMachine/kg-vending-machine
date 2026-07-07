"""notice-refinement와 develop 마이그레이션 체인 병합

Revision ID: cd87fc1d75a7
Revises: 0f54ab544cb2, f42111cd547f
Create Date: 2026-07-07 11:05:07.399723

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cd87fc1d75a7'
down_revision: Union[str, Sequence[str], None] = ('0f54ab544cb2', 'f42111cd547f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

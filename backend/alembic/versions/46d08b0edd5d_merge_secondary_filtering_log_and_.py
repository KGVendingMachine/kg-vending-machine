"""merge secondary_filtering_log and notice_bookmark heads

Revision ID: 46d08b0edd5d
Revises: 9f3c1a2b7d64, 681ee3c17bf0
Create Date: 2026-07-14 15:33:36.440768

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "46d08b0edd5d"
down_revision: Union[str, Sequence[str], None] = ("9f3c1a2b7d64", "681ee3c17bf0")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

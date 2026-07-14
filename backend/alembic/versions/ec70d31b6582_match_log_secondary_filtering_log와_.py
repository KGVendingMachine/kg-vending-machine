"""match_log secondary_filtering_log와 notice_bookmark 추천 컨텍스트 브랜치 병합

Revision ID: ec70d31b6582
Revises: 681ee3c17bf0, 9f3c1a2b7d64
Create Date: 2026-07-14 18:22:58.741347

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "ec70d31b6582"
down_revision: Union[str, Sequence[str], None] = ("681ee3c17bf0", "9f3c1a2b7d64")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

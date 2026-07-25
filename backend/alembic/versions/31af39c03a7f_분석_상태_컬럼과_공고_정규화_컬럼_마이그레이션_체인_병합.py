"""분석 상태 컬럼과 공고 정규화 컬럼 마이그레이션 체인 병합

Revision ID: 31af39c03a7f
Revises: 088335bac40c, a9c4f2d1e8b6
Create Date: 2026-07-11 11:38:19.517335

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "31af39c03a7f"
down_revision: Union[str, Sequence[str], None] = ("088335bac40c", "a9c4f2d1e8b6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

"""notice source_url apply_url을 Text로 확장

Revision ID: 0f54ab544cb2
Revises: 5ca2a5204e5e
Create Date: 2026-07-07 10:02:17.768194

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0f54ab544cb2"
down_revision: Union[str, Sequence[str], None] = "e1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """실제 수집 중 500자 넘는 apply_url(구글폼 로그인 리다이렉트 URL)
    때문에 저장이 실패하는 것을 확인하고 확장함."""
    op.alter_column(
        "notice", "source_url", existing_type=sa.VARCHAR(length=500), type_=sa.Text()
    )
    op.alter_column(
        "notice", "apply_url", existing_type=sa.VARCHAR(length=500), type_=sa.Text()
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "notice", "apply_url", existing_type=sa.Text(), type_=sa.VARCHAR(length=500)
    )
    op.alter_column(
        "notice", "source_url", existing_type=sa.Text(), type_=sa.VARCHAR(length=500)
    )

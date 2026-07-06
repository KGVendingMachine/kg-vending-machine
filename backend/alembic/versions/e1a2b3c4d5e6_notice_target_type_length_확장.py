"""notice_target_type 길이 확장

Revision ID: e1a2b3c4d5e6
Revises: c8e02bc78b38
Create Date: 2026-07-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "c8e02bc78b38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """신청대상 원문이 50자를 넘어도 저장할 수 있도록 확장한다."""
    op.alter_column(
        "notice_target_type",
        "target_type",
        existing_type=sa.String(length=50),
        type_=sa.String(length=255),
        existing_nullable=False,
    )


def downgrade() -> None:
    """기존 50자 제한으로 되돌린다."""
    op.alter_column(
        "notice_target_type",
        "target_type",
        existing_type=sa.String(length=255),
        type_=sa.String(length=50),
        existing_nullable=False,
    )

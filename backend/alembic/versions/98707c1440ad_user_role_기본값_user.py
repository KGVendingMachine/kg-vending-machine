"""user role 기본값 USER

Revision ID: 98707c1440ad
Revises: 48fdaebc1be0
Create Date: 2026-07-07 10:43:35.479609

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "98707c1440ad"
down_revision: Union[str, Sequence[str], None] = "48fdaebc1be0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    role은 인가(권한) 판단의 기준이라 항상 값이 있어야 한다. 신규 가입은
    USER로 시작하고, ADMIN은 별도로 수동 지정한다. 기존 NULL 행을 먼저
    USER로 채운 뒤 server_default와 NOT NULL을 적용한다(status 컬럼과
    동일한 규칙).
    """
    op.execute("UPDATE \"user\" SET role = 'USER' WHERE role IS NULL")
    op.alter_column(
        "user",
        "role",
        existing_type=sa.String(255),
        type_=sa.String(20),
        server_default="USER",
        nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "user",
        "role",
        existing_type=sa.String(20),
        type_=sa.String(255),
        server_default=None,
        nullable=True,
    )

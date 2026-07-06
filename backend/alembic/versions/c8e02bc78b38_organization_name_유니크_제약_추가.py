"""organization name 유니크 제약 추가

Revision ID: c8e02bc78b38
Revises: 29cfff37b315
Create Date: 2026-07-06 17:23:24.603771

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e02bc78b38"
down_revision: Union[str, Sequence[str], None] = "29cfff37b315"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint("uq_organization_name", "organization", ["name"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_organization_name", "organization", type_="unique")

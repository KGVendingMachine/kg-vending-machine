"""notice_attachment notice_id file_url 유니크 제약 추가

Revision ID: 595adb975c89
Revises: cd87fc1d75a7
Create Date: 2026-07-07 14:28:37.978778

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "595adb975c89"
down_revision: Union[str, Sequence[str], None] = "cd87fc1d75a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(
        "uq_notice_attachment_notice_id_file_url",
        "notice_attachment",
        ["notice_id", "file_url"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_notice_attachment_notice_id_file_url",
        "notice_attachment",
        type_="unique",
    )

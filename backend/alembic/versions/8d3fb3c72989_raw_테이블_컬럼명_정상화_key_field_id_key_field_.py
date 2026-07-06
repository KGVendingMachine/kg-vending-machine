"""raw 테이블 컬럼명 정상화 (Key,Field,id -> key,field,notice_id)

Revision ID: 8d3fb3c72989
Revises: 9b809fce1a26
Create Date: 2026-07-05 21:10:50.201994

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8d3fb3c72989"
down_revision: Union[str, Sequence[str], None] = "9b809fce1a26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("bizinfo_raw", "kstartup_raw", "refined_column")


def upgrade() -> None:
    """Upgrade schema.

    처음 스키마를 만들 때 ERD 툴이 컬럼명을 "Key"/"Field"/"id"로 만들어서
    파이썬 속성명(key/field/notice_id)과 어긋나 있었다. 데이터를 보존하는
    실제 rename(alter_column)으로 이름만 정상화한다. drop+add 방식으로
    하면 NOT NULL 컬럼에서 기존 데이터가 날아간다.
    """
    for table in TABLES:
        op.alter_column(table, "Key", new_column_name="key")
        op.alter_column(table, "Field", new_column_name="field")
        op.alter_column(table, "id", new_column_name="notice_id")


def downgrade() -> None:
    """Downgrade schema."""
    for table in TABLES:
        op.alter_column(table, "key", new_column_name="Key")
        op.alter_column(table, "field", new_column_name="Field")
        op.alter_column(table, "notice_id", new_column_name="id")

"""notice.target_allows_prestartup 컬럼 추가 (업력 축 구조화)

K-Startup biz_enyy를 구조화해 1차 필터(업력 축)가 SQL/컬럼으로 판정할 수
있게 한다. target_business_years_max(기존 컬럼)는 'N년미만' 최댓값,
target_allows_prestartup은 예비창업자 허용 여부. 둘 다 NULL이면 업력 제한
정보 없음(permissive).

Revision ID: b3d9f1c04e27
Revises: 46d08b0edd5d
Create Date: 2026-07-15 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b3d9f1c04e27"
down_revision: Union[str, Sequence[str], None] = "46d08b0edd5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "notice",
        sa.Column("target_allows_prestartup", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("notice", "target_allows_prestartup")

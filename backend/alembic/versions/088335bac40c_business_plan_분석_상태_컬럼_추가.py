"""business_plan 분석 상태 컬럼 추가

Revision ID: 088335bac40c
Revises: 7deb161d8f0e
Create Date: 2026-07-11 09:06:05.717157

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '088335bac40c'
down_revision: Union[str, Sequence[str], None] = '7deb161d8f0e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # autogenerate가 모델에 정의되지 않은 기존 유니크 제약(category_mapping,
    # notice_attachment — 마이그레이션에서 직접 만든 것)을 삭제 대상으로 잘못
    # 감지해서, 이 변경과 무관한 drop_constraint는 제거했다.
    op.add_column('business_plan', sa.Column('analysis_status', sa.String(length=20), nullable=True))
    op.add_column('business_plan', sa.Column('analysis_step', sa.String(length=20), nullable=True))
    op.add_column('business_plan', sa.Column('analysis_error', sa.Text(), nullable=True))
    op.add_column('business_plan', sa.Column('analysis_started_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('business_plan', 'analysis_started_at')
    op.drop_column('business_plan', 'analysis_error')
    op.drop_column('business_plan', 'analysis_step')
    op.drop_column('business_plan', 'analysis_status')

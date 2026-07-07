"""user kakao_id 유니크 제약 추가

Revision ID: 48fdaebc1be0
Revises: cd87fc1d75a7
Create Date: 2026-07-06 18:46:47.530298

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "48fdaebc1be0"
down_revision: Union[str, Sequence[str], None] = "cd87fc1d75a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    한 카카오 계정은 우리 서비스 유저 1명에 대응해야 한다. 로그인 시
    kakao_id로 기존 유저를 찾는데, 유니크 제약이 없으면 동시 로그인
    요청이 겹칠 때 같은 kakao_id로 유저가 중복 생성될 수 있다. 이
    제약으로 DB 차원에서 막고, 유저 upsert의 ON CONFLICT 기준으로 쓴다.
    """
    op.create_unique_constraint("uq_user_kakao_id", "user", ["kakao_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_user_kakao_id", "user", type_="unique")

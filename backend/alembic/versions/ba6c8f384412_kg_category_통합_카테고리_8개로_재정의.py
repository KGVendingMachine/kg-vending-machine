"""kg_category 통합 카테고리 8개로 재정의

Revision ID: ba6c8f384412
Revises: e1a2b3c4d5e6
Create Date: 2026-07-06 18:17:04.639835

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ba6c8f384412"
down_revision: Union[str, Sequence[str], None] = "e1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# SqlEnum(CategoryName, name="category_name")에 values_callable을 안 줘서
# DB에는 한글 값이 아니라 파이썬 enum 멤버 "이름"이 저장된다
# (예: CategoryName.FUND -> "자금"이 아니라 "FUND").
OLD_VALUES = (
    "FUND",
    "TECH",
    "MANPOWER",
    "EXPORT",
    "SALES",
    "STARTUP",
    "MANAGEMENT",
    "COMMERCIALIZATION",
    "INCUBATION",
    "EDUCATION",
    "EVENT",
)
NEW_VALUES = (
    "FUND",
    "RND_TECH",
    "EXPORT_GLOBAL",
    "MANPOWER",
    "FACILITY_SPACE_INCUBATION",
    "MENTORING_CONSULTING",
    "EDUCATION_EVENT_NETWORKING",
    "ETC",
)


def upgrade() -> None:
    """기업마당/K-Startup 두 체계를 8개 통합 카테고리로 합치기로 한
    팀 결정(2026-07-06)을 반영한다.

    kg_category.name은 Postgres 네이티브 ENUM(category_name)이라 값
    목록을 그냥 바꿀 수 없다. 이 시점에 kg_category/category_mapping이
    비어 있는 것을 확인하고, 컬럼을 text로 바꿨다가 기존 타입을 지우고
    새 타입으로 다시 바꾸는 방식을 쓴다 (데이터가 있었다면 값 매핑이
    필요했겠지만, 지금은 비어 있어 그대로 캐스팅해도 안전하다).
    """
    op.execute(
        "ALTER TABLE kg_category ALTER COLUMN name TYPE VARCHAR USING name::text"
    )
    op.execute("DROP TYPE category_name")
    values_sql = ", ".join(f"'{v}'" for v in NEW_VALUES)
    op.execute(f"CREATE TYPE category_name AS ENUM ({values_sql})")
    op.execute(
        "ALTER TABLE kg_category ALTER COLUMN name TYPE category_name "
        "USING name::category_name"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "ALTER TABLE kg_category ALTER COLUMN name TYPE VARCHAR USING name::text"
    )
    op.execute("DROP TYPE category_name")
    values_sql = ", ".join(f"'{v}'" for v in OLD_VALUES)
    op.execute(f"CREATE TYPE category_name AS ENUM ({values_sql})")
    op.execute(
        "ALTER TABLE kg_category ALTER COLUMN name TYPE category_name "
        "USING name::category_name"
    )

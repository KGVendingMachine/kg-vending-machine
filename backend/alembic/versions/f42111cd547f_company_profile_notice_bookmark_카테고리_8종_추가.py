"""company_profile 상세화, notice 요약/카테고리 단순화, notice_bookmark 추가

Revision ID: f42111cd547f
Revises: 8d3fb3c72989
Create Date: 2026-07-07 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f42111cd547f"
down_revision: Union[str, Sequence[str], None] = "8d3fb3c72989"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# category_name enum은 CategoryName 파이썬 enum의 .name(멤버명)을 저장한다 (.value인
# 한글 표시값이 아님) — 2267183964a7_add_initial_schema.py가 만든
# sa.Enum('FUND', 'TECH', ...) 그대로의 관례를 따른다.
OLD_CATEGORY_MEMBER_NAMES = (
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
NEW_CATEGORY_MEMBER_NAMES = (
    "FUND",
    "TECH",
    "EXPORT",
    "MANPOWER",
    "FACILITY",
    "CONSULTING",
    "EDUCATION_EVENT",
    "ETC",
)


def upgrade() -> None:
    """Upgrade schema."""
    # 0) 공고 1개 = 카테고리 1개로 단순화하면서 더 이상 쓰지 않는 다대다 매핑 제거
    op.drop_table("notice_category_map")

    # 1) category_name enum을 문서(docs/notice-category-mapping.md) 기준 8종으로 재정의.
    #    프로토타입 단계라 실데이터가 없다는 전제로 기존 카테고리 데이터를 비우고 다시 채운다.
    #    운영 데이터가 쌓인 뒤라면 TRUNCATE 대신 값 매핑표를 만들어 UPDATE로 이관할 것.
    op.execute("TRUNCATE TABLE category_mapping")
    op.execute("TRUNCATE TABLE kg_category CASCADE")
    op.execute("ALTER TYPE category_name RENAME TO category_name_old")
    op.execute(
        "CREATE TYPE category_name AS ENUM ("
        + ", ".join(f"'{name}'" for name in NEW_CATEGORY_MEMBER_NAMES)
        + ")"
    )
    op.execute(
        "ALTER TABLE kg_category "
        "ALTER COLUMN name TYPE category_name USING name::text::category_name"
    )
    op.execute("DROP TYPE category_name_old")
    # asyncpg는 bind parameter(VARCHAR)를 enum 컬럼에 암시적으로 캐스팅해주지 않으므로
    # (DatatypeMismatchError), 파라미터 바인딩 없는 리터럴 INSERT로 삽입한다.
    op.execute(
        "INSERT INTO kg_category (name) VALUES "
        + ", ".join(f"('{name}')" for name in NEW_CATEGORY_MEMBER_NAMES)
    )

    # 2) 공고는 카테고리를 정확히 1개만 가진다 (다대다 대신 직접 FK)
    op.add_column("notice", sa.Column("category_id", sa.Integer(), nullable=True))
    op.create_foreign_key(None, "notice", "kg_category", ["category_id"], ["id"])

    # 3) 기업 프로필 상세화: 대표자명 / 사업자등록번호 / 기업 규모
    op.add_column(
        "company_profile",
        sa.Column("representative_name", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "company_profile",
        sa.Column(
            "business_registration_number", sa.String(length=20), nullable=True
        ),
    )
    op.add_column(
        "company_profile",
        sa.Column("company_size", sa.String(length=20), nullable=True),
    )

    # 4) 공고 요약: 지원금액 라벨 / 구조화된 요약 포인트
    op.add_column(
        "notice", sa.Column("amount_label", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "notice",
        sa.Column(
            "summary_points_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # 5) 북마크: user × notice, 로그인 사용자당 같은 공고는 한 번만 북마크
    op.create_table(
        "notice_bookmark",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("notice_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["notice_id"], ["notice.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "notice_id", name="uq_notice_bookmark_user_notice"
        ),
    )


def downgrade() -> None:
    """Downgrade schema.

    카테고리 데이터는 upgrade에서 비우고 다시 채우므로, downgrade 후에도
    upgrade 이전에 있던 kg_category/category_mapping 데이터는 복구되지 않는다.
    """
    op.drop_table("notice_bookmark")
    op.drop_column("notice", "summary_points_json")
    op.drop_column("notice", "amount_label")
    op.drop_column("company_profile", "company_size")
    op.drop_column("company_profile", "business_registration_number")
    op.drop_column("company_profile", "representative_name")

    op.drop_constraint("notice_category_id_fkey", "notice", type_="foreignkey")
    op.drop_column("notice", "category_id")

    op.execute("TRUNCATE TABLE kg_category CASCADE")
    op.execute("ALTER TYPE category_name RENAME TO category_name_new")
    op.execute(
        "CREATE TYPE category_name AS ENUM ("
        + ", ".join(f"'{name}'" for name in OLD_CATEGORY_MEMBER_NAMES)
        + ")"
    )
    op.execute(
        "ALTER TABLE kg_category "
        "ALTER COLUMN name TYPE category_name USING name::text::category_name"
    )
    op.execute("DROP TYPE category_name_new")

    op.create_table(
        "notice_category_map",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("notice_id", sa.Integer(), nullable=False),
        sa.Column("mapping_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["mapping_id"], ["category_mapping.id"]),
        sa.ForeignKeyConstraint(["notice_id"], ["notice.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

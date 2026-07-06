"""카테고리 8개 및 원본-통합 매핑 시드 데이터

Revision ID: 5ca2a5204e5e
Revises: ba6c8f384412
Create Date: 2026-07-06 18:21:32.640598

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5ca2a5204e5e"
down_revision: Union[str, Sequence[str], None] = "ba6c8f384412"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 팀에서 합의한 "두 체계 -> 통합 카테고리 매핑표"(2026-07-06)를 그대로 옮긴 것.
# 원본 라벨은 기획 문서에 적힌 설명 그대로이며, 기업마당
# pldirSportRealmLclasCodeNm/실제 K-Startup supt_biz_clsfc 값과 완전히
# 일치하는지는 검증되지 않았다. COL-003(카테고리 분류)을 실제로 구현할 때
# 실 API 값과 대조해서 필요하면 raw_category를 더 추가/수정해야 한다.
CATEGORY_MAPPING: dict[str, list[str]] = {
    "FUND": ["기업마당 금융", "K-Startup 융자·사업화"],
    "RND_TECH": ["기업마당 기술", "K-Startup 기술개발(R&D)"],
    "EXPORT_GLOBAL": ["기업마당 수출·내수", "K-Startup 글로벌(판로·해외진출)"],
    "MANPOWER": ["기업마당 인력", "K-Startup 인력"],
    "FACILITY_SPACE_INCUBATION": ["K-Startup 시설·공간·보육"],
    "MENTORING_CONSULTING": [
        "기업마당 경영(컨설팅류)",
        "K-Startup 멘토링·컨설팅·교육(컨설팅류)",
    ],
    "EDUCATION_EVENT_NETWORKING": [
        "K-Startup 행사·네트워크",
        "K-Startup 멘토링·컨설팅·교육(교육류)",
    ],
    "ETC": ["기업마당 기타·경영(잔여)"],
}


def upgrade() -> None:
    conn = op.get_bind()

    kg_category = sa.table(
        "kg_category",
        sa.column("id", sa.Integer),
        sa.column("name", sa.Enum(name="category_name")),
    )
    category_mapping = sa.table(
        "category_mapping",
        sa.column("id", sa.Integer),
        sa.column("raw_category", sa.String),
        sa.column("category_id", sa.Integer),
    )

    category_ids: dict[str, int] = {}
    for name in CATEGORY_MAPPING:
        result = conn.execute(
            kg_category.insert().values(name=name).returning(kg_category.c.id)
        )
        category_ids[name] = result.scalar_one()

    for name, raw_categories in CATEGORY_MAPPING.items():
        for raw_category in raw_categories:
            conn.execute(
                category_mapping.insert().values(
                    raw_category=raw_category, category_id=category_ids[name]
                )
            )


def downgrade() -> None:
    op.execute("DELETE FROM category_mapping")
    op.execute("DELETE FROM kg_category")

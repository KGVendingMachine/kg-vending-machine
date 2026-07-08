"""공고 카테고리 매핑 시드 데이터 및 유니크 제약 추가

Revision ID: 0756e6c105fe
Revises: 595adb975c89
Create Date: 2026-07-07 16:18:58.800221

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0756e6c105fe"
down_revision: Union[str, Sequence[str], None] = "595adb975c89"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# raw_category는 출처 접두어(BIZINFO:/KSTARTUP:)를 붙여 저장한다. category_mapping에
# 출처를 구분하는 컬럼이 따로 없어서, 두 출처의 원본값이 우연히 같은 문자열이어도
# (예: 둘 다 "인력") 서로 다른 행으로 명확히 구분하기 위함이다.
#
# 기업마당은 대분류(pldirSportRealmLclasCodeNm)만으로 충분한 값이 대부분이지만,
# "경영" 대분류는 docs/notice-category-mapping.md가 컨설팅류/잔여로 나누라고 한
# 것을 실제로 구분할 방법이 대분류만으로는 없어(실측 확인), 중분류
# (pldirSportRealmMlsfcCodeNm)를 대신 키로 쓴다. "경영:컨설팅"만 멘토링·컨설팅으로
# 보내고 나머지 경영 중분류는 전부 기타(잔여)로 보낸다 (문서의 "잔여" 표현 그대로).
#
# 문서 매핑표에 없던 값(기업마당 "창업", K-Startup "창업교육")은 문서의 적용 원칙
# ("가장 가까운 통합 카테고리에 매핑")에 따라 판단한 것 — 확정된 팀 결정이 아니라
# 추후 재검토 가능한 임시 판단이다.
SEED_ROWS = [
    # 기업마당 (대분류 기준, "경영"만 중분류로 세분화)
    ("BIZINFO:금융", "FUND"),
    ("BIZINFO:기술", "TECH"),
    ("BIZINFO:수출", "EXPORT"),
    ("BIZINFO:내수", "EXPORT"),
    ("BIZINFO:인력", "MANPOWER"),
    ("BIZINFO:기타", "ETC"),
    ("BIZINFO:창업", "ETC"),  # 문서에 명시 안 됨 — 임시 판단, 재검토 필요
    ("BIZINFO:경영:컨설팅", "CONSULTING"),
    ("BIZINFO:경영:디자인/상품화/사업화", "ETC"),
    ("BIZINFO:경영:시설/입지지원", "ETC"),
    ("BIZINFO:경영:정보화지원", "ETC"),
    ("BIZINFO:경영:교육", "ETC"),
    # K-Startup (supt_biz_clsfc 기준, 중분류 필드가 없어 태그 전체를 그대로 씀)
    ("KSTARTUP:정책자금", "FUND"),
    ("KSTARTUP:융자ㆍ보증", "FUND"),
    ("KSTARTUP:사업화", "FUND"),
    ("KSTARTUP:기술개발(R&D)", "TECH"),
    ("KSTARTUP:판로ㆍ해외진출", "EXPORT"),
    ("KSTARTUP:글로벌", "EXPORT"),
    ("KSTARTUP:인력", "MANPOWER"),
    ("KSTARTUP:시설ㆍ공간ㆍ보육", "FACILITY"),
    ("KSTARTUP:멘토링ㆍ컨설팅ㆍ교육", "CONSULTING"),
    ("KSTARTUP:행사ㆍ네트워크", "EDUCATION_EVENT"),
    ("KSTARTUP:창업교육", "EDUCATION_EVENT"),  # 문서에 명시 안 됨 — 임시 판단
]


def upgrade() -> None:
    bind = op.get_bind()
    op.create_unique_constraint(
        "uq_category_mapping_raw_category", "category_mapping", ["raw_category"]
    )
    for raw_category, category_name in SEED_ROWS:
        bind.execute(
            text(
                "INSERT INTO category_mapping (raw_category, category_id) "
                "SELECT :raw_category, id FROM kg_category WHERE name = :name"
            ),
            {"raw_category": raw_category, "name": category_name},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for raw_category, _ in SEED_ROWS:
        bind.execute(
            text("DELETE FROM category_mapping WHERE raw_category = :raw_category"),
            {"raw_category": raw_category},
        )
    op.drop_constraint(
        "uq_category_mapping_raw_category", "category_mapping", type_="unique"
    )

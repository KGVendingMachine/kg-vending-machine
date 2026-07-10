"""kg_category name 한글 값으로 저장

Revision ID: 7deb161d8f0e
Revises: 8c2d2294fd17
Create Date: 2026-07-09 13:37:42.341726

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7deb161d8f0e"
down_revision: Union[str, Sequence[str], None] = "8c2d2294fd17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# category_name enum이 지금까지 CategoryName 파이썬 enum의 .name(영문 멤버명,
# 예: FUND)을 저장해왔는데(f42111cd547f 참고), 화면에 그대로 노출 가능한
# 한글 표시값(.value)으로 바꾼다. 이번엔 실데이터(notice.category_id 등)가
# 이미 쌓여있어 TRUNCATE로 비울 수 없으므로, id는 그대로 두고 라벨만
# UPDATE로 이관한다.
NAME_KO_BY_EN = {
    "FUND": "자금",
    "TECH": "R&D·기술",
    "EXPORT": "수출·글로벌",
    "MANPOWER": "인력",
    "FACILITY": "시설·공간·보육",
    "CONSULTING": "멘토링·컨설팅",
    "EDUCATION_EVENT": "교육·행사·네트워킹",
    "ETC": "기타",
}


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE category_name RENAME TO category_name_old")
    op.execute(
        "CREATE TYPE category_name AS ENUM ("
        + ", ".join(f"'{ko}'" for ko in NAME_KO_BY_EN.values())
        + ")"
    )
    case_expr = " ".join(f"WHEN '{en}' THEN '{ko}'" for en, ko in NAME_KO_BY_EN.items())
    op.execute(
        "ALTER TABLE kg_category "
        "ALTER COLUMN name TYPE category_name "
        f"USING (CASE name::text {case_expr} END)::category_name"
    )
    op.execute("DROP TYPE category_name_old")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TYPE category_name RENAME TO category_name_new")
    op.execute(
        "CREATE TYPE category_name AS ENUM ("
        + ", ".join(f"'{en}'" for en in NAME_KO_BY_EN.keys())
        + ")"
    )
    case_expr = " ".join(f"WHEN '{ko}' THEN '{en}'" for en, ko in NAME_KO_BY_EN.items())
    op.execute(
        "ALTER TABLE kg_category "
        "ALTER COLUMN name TYPE category_name "
        f"USING (CASE name::text {case_expr} END)::category_name"
    )
    op.execute("DROP TYPE category_name_new")

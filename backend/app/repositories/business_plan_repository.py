from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_plan import BusinessPlan


async def save_raw_text(
    session: AsyncSession, business_plan_id: int, raw_text: str, file_type: str
) -> None:
    """추출한 원문 텍스트를 기존 business_plan 행에 반영한다.

    business_plan 행 자체는 업로드 API(Backend 담당)가 먼저 만들어 둔다고
    가정하고, 여기서는 OCR/텍스트 추출 결과만 채운다.
    """
    await session.execute(
        update(BusinessPlan)
        .where(BusinessPlan.id == business_plan_id)
        .values(raw_text=raw_text, file_type=file_type)
    )

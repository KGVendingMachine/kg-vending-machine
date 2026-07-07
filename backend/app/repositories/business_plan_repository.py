from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_plan import BusinessPlan


async def save_raw_text(
    session: AsyncSession, business_plan_id: int, raw_text: str, file_type: str
) -> None:
    """추출한 원문 텍스트를 기존 business_plan 행에 반영한다.

    business_plan 행 자체는 업로드 API(Backend 담당)가 먼저 만들어 둔다고
    가정하고, 여기서는 OCR/텍스트 추출 결과만 채운다.

    존재하지 않는 business_plan_id가 들어오면 UPDATE는 0행에 적용되고
    조용히 성공한 것처럼 끝나서, raw_text가 왜 안 채워졌는지 나중에
    추적하기 어렵다. rowcount를 확인해 즉시 에러로 드러낸다.
    """
    result = await session.execute(
        update(BusinessPlan)
        .where(BusinessPlan.id == business_plan_id)
        .values(raw_text=raw_text, file_type=file_type)
    )
    if result.rowcount == 0:
        raise ValueError(
            f"save_raw_text: business_plan_id={business_plan_id}가 존재하지 않습니다"
        )

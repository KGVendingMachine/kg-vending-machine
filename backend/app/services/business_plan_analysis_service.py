"""
services/business_plan_analysis_service.py

사업계획서 분석 오케스트레이션: OCR → raw_text 저장(커밋) → 정규화(analysis_json 저장).

OCR 결과(raw_text)를 정규화 전에 먼저 커밋한다. 정규화(LLM)가 실패해도 비싼
CLOVA OCR 결과는 DB에 남아, 재시도 시 재OCR 없이 정규화만 다시 돌릴 수 있다.
외부 호출(OCR=CLOVA, 정규화=LLM)은 테스트를 위해 함수로 주입받는다.
"""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.business_plan_repository import (
    BusinessPlanNotFoundError,
    get_by_id,
    save_raw_text,
)
from app.schemas.business_plan import NormalizedBusinessPlanSchema
from app.schemas.business_plan_analysis import AnalysisStep
from app.services.business_plan_service import (
    NormalizationOutcome,
    normalize_business_plan,
)

ExtractFn = Callable[[str], Awaitable[tuple[str, str]]]
NormalizeFn = Callable[[str], Awaitable[NormalizedBusinessPlanSchema]]
OnStepFn = Callable[[AnalysisStep], Awaitable[None]]


class NoUploadedFileError(Exception):
    """분석하려는 business_plan에 업로드된 파일(file_url)이 없을 때."""

    def __init__(self, business_plan_id: int):
        self.business_plan_id = business_plan_id
        super().__init__(f"BusinessPlan {business_plan_id} has no uploaded file")


async def run_analysis(
    session: AsyncSession,
    business_plan_id: int,
    *,
    extract_fn: ExtractFn,
    normalize_fn: NormalizeFn,
    on_step: OnStepFn | None = None,
) -> NormalizationOutcome:
    """업로드된 파일을 OCR한 뒤 정규화한다.

    1. file_url의 파일을 OCR → raw_text/file_type 저장 후 커밋(먼저 확정)
    2. 방금 추출한 텍스트로 정규화 → analysis_json 저장

    raw_text가 이미 있으면(이전 실행에서 OCR까지 성공하고 정규화만 실패한
    경우) 1을 건너뛰고 정규화부터 시작한다 — 실패 후 재시도가 비싼 CLOVA
    OCR을 다시 부르지 않게. 업로드는 매번 새 행을 만들므로 raw_text가 있다는
    건 같은 파일을 이미 추출했다는 뜻이다.

    on_step은 진행 단계를 알리는 선택적 콜백(business_plan 행의 잡 상태
    갱신용 — DB를 쓰므로 async)이다.
    """
    plan = await get_by_id(session, business_plan_id)
    if plan is None:
        raise BusinessPlanNotFoundError(business_plan_id)
    if not plan.file_url:
        raise NoUploadedFileError(business_plan_id)

    if plan.raw_text:
        text = plan.raw_text
    else:
        if on_step is not None:
            await on_step(AnalysisStep.EXTRACTING)
        text, file_type = await extract_fn(plan.file_url)
        await save_raw_text(session, business_plan_id, text, file_type)
        # OCR 결과를 정규화 전에 확정한다. 아래 정규화가 실패해도 raw_text는 남는다.
        await session.commit()

    if on_step is not None:
        await on_step(AnalysisStep.NORMALIZING)
    return await normalize_business_plan(
        session,
        business_plan_id=business_plan_id,
        normalize_fn=normalize_fn,
        extracted_text=text,
    )

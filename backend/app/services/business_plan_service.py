"""
services/business_plan_service.py

NRM-001: 사업계획서 정규화 오케스트레이션.
DB 조회/저장은 repositories.business_plan_repository에 위임한다.

실제 LLM 호출(ai/ 레이어)은 아직 구현되지 않았으므로 normalize_fn으로 주입받는다.
ai/ 구현이 준비되면 호출하는 쪽(라우터/작업 실행기)에서 실제 함수를 넘기면 됨.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.business_plan_repository import (
    get_raw_text,
    save_normalization_result,
)
from app.schemas.business_plan import NormalizedBusinessPlanSchema, ValidationResult

NormalizeFn = Callable[[str], Awaitable[NormalizedBusinessPlanSchema]]

# PSST 축(문제/실현가능성/성장전략/팀)별로 최소 이 필드는 채워져야 유효하다고 판단.
# 재정규화 정책과 마찬가지로 팀 논의 후 확정 필요 (TODO).
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "problem": ("background",),
    "solution": ("summary",),
    "funding": ("scale_up_strategy",),
    "team": ("capabilities",),
}


class NoSourceTextError(Exception):
    """정규화할 원문이 없을 때 (extracted_text도, DB raw_text도 없음)."""

    def __init__(self, business_plan_id: int):
        self.business_plan_id = business_plan_id
        super().__init__(f"BusinessPlan {business_plan_id} has no text to normalize")


@dataclass
class NormalizationOutcome:
    normalized: NormalizedBusinessPlanSchema
    validation_result: ValidationResult
    analyzed_at: datetime


def validate_normalized(normalized: NormalizedBusinessPlanSchema) -> ValidationResult:
    """REQUIRED_FIELDS에 정의된 필드가 비어있는지 확인해서 ValidationResult 생성."""
    missing: list[str] = []
    for category, fields in REQUIRED_FIELDS.items():
        section = getattr(normalized, category)
        for field in fields:
            if not getattr(section, field):
                missing.append(f"{category}.{field}")
    return ValidationResult(is_valid=not missing, missing_required_fields=missing)


async def normalize_business_plan(
    session: AsyncSession,
    business_plan_id: int,
    normalize_fn: NormalizeFn,
    extracted_text: str | None = None,
) -> NormalizationOutcome:
    """
    1. 정규화 대상 원문 확보 (extracted_text가 있으면 우선 사용, 없으면 DB raw_text 조회)
    2. normalize_fn으로 LLM 정규화 호출
    3. 결과 검증
    4. DB에 저장

    BusinessPlanNotFoundError는 repository에서 그대로 전파됨.
    """
    source_text = extracted_text
    if source_text is None:
        source_text = await get_raw_text(session, business_plan_id)

    if not source_text:
        raise NoSourceTextError(business_plan_id)

    normalized = await normalize_fn(source_text)
    validation_result = validate_normalized(normalized)

    plan = await save_normalization_result(
        session,
        business_plan_id=business_plan_id,
        normalized_json=normalized.model_dump(),
    )

    return NormalizationOutcome(
        normalized=normalized,
        validation_result=validation_result,
        analyzed_at=plan.analyzed_at,
    )

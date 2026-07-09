from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.ai.normalizer import AiNormalizationError, normalize_text
from app.schemas.business_plan import NormalizedBusinessPlanSchema, ValidationResult
from app.services.business_plan_service import validate_normalized
from app.services.sample_business_plan_loader import (
    SampleBusinessPlanError,
    load_sample_business_plan,
)

router = APIRouter(
    prefix="/business-plans/samples",
    tags=["business-plan-samples"],
)


class SampleNormalizationRequest(BaseModel):
    sample_index: int = Field(default=0, ge=0)
    sample_path: str | None = Field(
        default=None,
        description="Optional local JSON path. Defaults to BUSINESS_PLAN_SAMPLE_JSON_PATH.",
    )


class SampleNormalizationResponse(BaseModel):
    sample_index: int
    file_name: str | None = None
    file_type: str | None = None
    char_count: int | None = None
    normalized_json: NormalizedBusinessPlanSchema
    validation_result: ValidationResult


@router.post(
    "/normalizations",
    response_model=SampleNormalizationResponse,
    status_code=status.HTTP_200_OK,
)
async def normalize_sample_business_plan(
    request: SampleNormalizationRequest,
) -> SampleNormalizationResponse:
    try:
        sample = load_sample_business_plan(
            sample_index=request.sample_index,
            sample_path=request.sample_path,
        )
        normalized = await normalize_text(sample.raw_text)
    except SampleBusinessPlanError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except AiNormalizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return SampleNormalizationResponse(
        sample_index=sample.sample_index,
        file_name=sample.file_name,
        file_type=sample.file_type,
        char_count=sample.char_count,
        normalized_json=normalized,
        validation_result=validate_normalized(normalized),
    )

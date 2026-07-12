from datetime import date

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.ai.normalizer import AiNormalizationError
from app.ai.notice_normalizer import normalize_notice_text
from app.schemas.business_plan import ValidationResult
from app.schemas.notice_normalization import NormalizedNoticeSchema
from app.services.notice_normalization_helpers import (
    build_notice_prompt_text,
    enrich_normalized_notice,
)
from app.services.notice_service import validate_normalized_notice
from app.services.sample_notice_loader import (
    SampleNotice,
    SampleNoticeError,
    load_sample_notice,
)

router = APIRouter(
    prefix="/notices/samples",
    tags=["notice-samples"],
)


class SampleNoticeNormalizationRequest(BaseModel):
    sample_index: int = Field(default=0, ge=0)
    sample_path: str | None = Field(
        default=None,
        description="선택적인 로컬 JSON 경로(data 디렉터리 내부 파일만 허용). 미지정 시 NOTICE_SAMPLE_JSON_PATH를 사용합니다.",
    )


class SampleNoticeNormalizationResponse(BaseModel):
    sample_index: int
    title: str | None = None
    source: str | None = None
    category: str | None = None
    status: str | None = None
    application_start_date: str | None = None
    application_end_date: str | None = None
    file_name: str | None = None
    file_type: str | None = None
    char_count: int
    normalized_json: NormalizedNoticeSchema
    validation_result: ValidationResult


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _build_sample_prompt_text(sample: SampleNotice) -> str:
    return build_notice_prompt_text(
        label="샘플",
        metadata={
            "sample_index": str(sample.sample_index),
            "title": sample.title or "",
            "source": sample.source or "",
            "category": sample.category or "",
            "status": sample.status or "",
            "application_start_date": sample.application_start_date or "",
            "application_end_date": sample.application_end_date or "",
            "file_name": sample.file_name or "",
            "file_type": sample.file_type or "",
        },
        raw_text=sample.raw_text,
    )


def _enrich_from_sample_metadata(
    sample: SampleNotice, normalized: NormalizedNoticeSchema
) -> NormalizedNoticeSchema:
    return enrich_normalized_notice(
        normalized,
        title=sample.title,
        source=sample.source,
        category=sample.category,
        status=sample.status,
        application_start_date=_parse_date(sample.application_start_date),
        application_end_date=_parse_date(sample.application_end_date),
        raw_text=sample.raw_text,
    )


@router.post(
    "/normalizations",
    response_model=SampleNoticeNormalizationResponse,
    status_code=status.HTTP_200_OK,
)
async def normalize_sample_notice(
    request: SampleNoticeNormalizationRequest,
) -> SampleNoticeNormalizationResponse:
    try:
        sample = load_sample_notice(
            sample_index=request.sample_index,
            sample_path=request.sample_path,
        )
        normalized = await normalize_notice_text(_build_sample_prompt_text(sample))
        normalized = _enrich_from_sample_metadata(sample, normalized)
    except SampleNoticeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except AiNormalizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return SampleNoticeNormalizationResponse(
        sample_index=sample.sample_index,
        title=sample.title,
        source=sample.source,
        category=sample.category,
        status=sample.status,
        application_start_date=sample.application_start_date,
        application_end_date=sample.application_end_date,
        file_name=sample.file_name,
        file_type=sample.file_type,
        char_count=sample.char_count,
        normalized_json=normalized,
        validation_result=validate_normalized_notice(
            normalized, source_text=sample.raw_text
        ),
    )

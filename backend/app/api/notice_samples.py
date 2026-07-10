import re
from datetime import date

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.ai.normalizer import AiNormalizationError
from app.ai.notice_normalizer import normalize_notice_text
from app.schemas.business_plan import ValidationResult
from app.schemas.notice_normalization import NormalizedNoticeSchema
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
        description="Optional local JSON path. Defaults to NOTICE_SAMPLE_JSON_PATH.",
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


def _build_sample_prompt_text(sample) -> str:
    metadata_lines = [
        f"sample_index: {sample.sample_index}",
        f"title: {sample.title or ''}",
        f"source: {sample.source or ''}",
        f"category: {sample.category or ''}",
        f"status: {sample.status or ''}",
        f"application_start_date: {sample.application_start_date or ''}",
        f"application_end_date: {sample.application_end_date or ''}",
        f"file_name: {sample.file_name or ''}",
        f"file_type: {sample.file_type or ''}",
    ]
    return (
        "샘플 메타데이터:\n"
        + "\n".join(metadata_lines)
        + "\n\n첨부파일/상세공고문 OCR 원문:\n"
        + sample.raw_text
    )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _append_unique(values: list[str], label: str) -> None:
    if label not in values:
        values.append(label)


def _has_keyword(values: list[str], keyword: str) -> bool:
    return any(keyword in value for value in values)


def _enrich_support_types(sample: SampleNotice, normalized: NormalizedNoticeSchema) -> None:
    support_text = "\n".join(
        [sample.raw_text, *normalized.support.support_content]
    )
    rules = (
        (("등록", "출원", "특허", "실용신안", "의장", "상표", "지적재산권", "산업재산권"), "지식재산권"),
        (("세미나", "교육", "워크숍", "워크샵"), "교육"),
        (("인증", "ISO", "이노비즈", "메인비즈", "벤처", "NET", "NEP", "KS", "CE", "RoHS", "FDA", "HACCP"), "인증지원"),
        (("홍보", "카탈로그", "동영상", "홈페이지", "제작"), "홍보지원"),
        (("시험", "성능시험", "신뢰성", "환경시험", "전자파", "소재시험", "제품성적서"), "시험/인증"),
        (("전문기술", "기술적 문제", "전문가", "컨설팅", "매칭"), "기술지원"),
        (("전투실험", "군 ", "국방", "방산", "방위산업"), "국방/방산"),
        (("비용", "지원금", "지원예산", "부담금", "만원", "억원", "%"), "자금지원"),
        (("수출", "해외", "무역", "글로벌"), "수출지원"),
        (("판로", "마케팅", "판매", "입점", "플래그십", "스토어"), "판로/마케팅"),
        (("공간", "시설", "회의실", "스튜디오", "대관"), "시설/공간"),
    )
    for keywords, label in rules:
        if any(keyword in support_text for keyword in keywords):
            _append_unique(normalized.support.support_type, label)


def _enrich_support_rates(sample: SampleNotice, normalized: NormalizedNoticeSchema) -> None:
    source_text = "\n".join([sample.raw_text, *normalized.support.support_content])
    has_support_90 = bool(re.search(r"90\s*%", source_text))
    has_self_payment_10 = bool(
        re.search(r"(기업부담금|자부담|부담금).{0,20}10\s*%", source_text)
    )

    if has_support_90:
        normalized.support.subsidy_rate = "90%"

    if has_self_payment_10:
        normalized.support.self_payment_required = True
        if not _has_keyword(normalized.matching.caution_points, "기업부담금"):
            _append_unique(
                normalized.matching.caution_points,
                "기업부담금은 공급가액의 10% 이상입니다.",
            )


def _enrich_from_sample_metadata(
    sample: SampleNotice, normalized: NormalizedNoticeSchema
) -> NormalizedNoticeSchema:
    normalized.basic.title = normalized.basic.title or sample.title
    normalized.basic.source = normalized.basic.source or sample.source
    normalized.basic.category = normalized.basic.category or sample.category
    normalized.basic.status = normalized.basic.status or sample.status
    normalized.application.start_date = normalized.application.start_date or _parse_date(
        sample.application_start_date
    )
    normalized.application.end_date = normalized.application.end_date or _parse_date(
        sample.application_end_date
    )

    if not normalized.application.method:
        if re.search(r"[\w.+-]+@[\w.-]+", sample.raw_text):
            normalized.application.method = "이메일 제출"
        elif "온라인" in sample.raw_text or "홈페이지" in sample.raw_text:
            normalized.application.method = "온라인 신청"

    if not normalized.application.submission_channel:
        if re.search(r"[\w.+-]+@[\w.-]+", sample.raw_text):
            normalized.application.submission_channel = "이메일"
        elif "온라인" in sample.raw_text or "홈페이지" in sample.raw_text:
            normalized.application.submission_channel = "온라인"

    company_size_keywords = (
        ("소상공인", "소상공인"),
        ("중소", "중소기업"),
        ("중견", "중견기업"),
        ("벤처", "벤처기업"),
    )
    existing_company_sizes = set(normalized.eligibility.target_company_size)
    for keyword, label in company_size_keywords:
        if keyword in sample.raw_text and label not in existing_company_sizes:
            normalized.eligibility.target_company_size.append(label)
            existing_company_sizes.add(label)

    _enrich_support_types(sample, normalized)
    _enrich_support_rates(sample, normalized)

    return normalized


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
        validation_result=validate_normalized_notice(normalized, source_text=sample.raw_text),
    )

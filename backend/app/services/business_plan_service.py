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
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_plan import BusinessPlan
from app.ocr.extract import SUPPORTED_UPLOAD_SUFFIXES, file_type_for_suffix
from app.repositories.business_plan_repository import (
    create,
    get_latest_by_company_profile,
    get_raw_text,
    save_normalization_result,
)
from app.repositories.company_repository import get_primary_by_user, upsert_primary
from app.schemas.business_plan import NormalizedBusinessPlanSchema, ValidationResult
from app.utils.file_storage import delete_stored_file, save_upload_file

NormalizeFn = Callable[[str], Awaitable[NormalizedBusinessPlanSchema]]


class UnsupportedFileTypeError(Exception):
    """OCR 파이프라인이 처리할 수 없는 확장자를 업로드했을 때."""

    def __init__(self, suffix: str):
        self.suffix = suffix
        super().__init__(f"지원하지 않는 파일 형식입니다: {suffix or '(확장자 없음)'}")


async def upload_business_plan(
    session: AsyncSession,
    *,
    user_id: int,
    file: UploadFile,
    storage_root: str,
    max_upload_size_bytes: int,
) -> BusinessPlan:
    """업로드 파일을 디스크에 저장하고 business_plan 행을 생성한다.

    OCR·정규화 같은 무거운 처리는 하지 않는다(이후 백그라운드 잡). 여기서는
    소유 기업 프로필 확보 → 확장자 검증 → 파일 저장 → 행 생성까지만 한다.

    업로드 우선 온보딩(#142): 프로필 작성 전에 업로드부터 하는 유저가
    기본 경로다. business_plan.company_profile_id가 NOT NULL이므로 프로필이
    없으면 빈 대표 프로필 행을 만들어 연결한다 — 이후 정규화가 이 행의 빈
    컬럼을 자동으로 채운다(company_service.autofill_profile_from_business_plan).
    """
    profile = await get_primary_by_user(session, user_id)
    if profile is None:
        profile = await upsert_primary(session, user_id, {})

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise UnsupportedFileTypeError(suffix)

    saved_path = await save_upload_file(file, storage_root, max_upload_size_bytes)
    try:
        plan = await create(
            session,
            company_profile_id=profile.id,
            title=file.filename,
            file_url=saved_path,
            file_type=file_type_for_suffix(suffix),
        )
        await session.commit()
    except BaseException:
        # DB 저장이 실패하면 방금 저장한 파일이 고아로 남지 않도록 정리한다.
        await session.rollback()
        delete_stored_file(saved_path)
        raise

    return plan


async def get_my_latest_business_plan(
    session: AsyncSession, user_id: int
) -> BusinessPlan | None:
    """로그인한 유저의 기업 프로필 기준 가장 최근 사업계획서를 반환한다."""
    profile = await get_primary_by_user(session, user_id)
    if profile is None:
        return None
    return await get_latest_by_company_profile(session, profile.id)


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

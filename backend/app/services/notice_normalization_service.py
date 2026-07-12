"""
services/notice_normalization_service.py

실제 DB에 저장된 공고를 대상으로 정규화(app.ai.notice_normalizer.normalize_notice_text
호출)를 실행하고 결과를 Notice에 저장한다. app/api/notice_samples.py(로컬 샘플 JSON
기준 테스트용 엔드포인트)와 같은 보완 규칙을 notice_normalization_helpers에서
공유해서 쓴다 — 다른 점은 원문을 로컬 파일이 아니라 실제 공고 메타데이터 +
OCR 결과(notice_ocr.py가 이미 채워둔 parsed_text)에서 가져온다는 것뿐이다.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.normalizer import AiNormalizationError
from app.ai.notice_normalizer import normalize_notice_text
from app.repositories.notice_repository import (
    get_notice_attachments,
    get_notice_detail,
    update_notice_normalization,
)
from app.schemas.business_plan import ValidationResult
from app.schemas.notice_normalization import NormalizedNoticeSchema
from app.services.notice_normalization_helpers import (
    build_notice_prompt_text,
    enrich_normalized_notice,
)
from app.services.notice_ocr_target import pick_ocr_target
from app.services.notice_service import validate_normalized_notice


class NoticeNormalizationError(Exception):
    """공고 정규화 실패에 대한 기본 예외."""


class NoticeNotFoundForNormalizationError(NoticeNormalizationError):
    """정규화 대상 공고를 찾을 수 없을 때 발생."""


class NoSourceTextForNormalizationError(NoticeNormalizationError):
    """정규화에 쓸 원문이 전혀 없을 때(OCR 텍스트도 summary_text도 없음) 발생."""


@dataclass
class NoticeNormalizationOutcome:
    normalized: NormalizedNoticeSchema
    validation_result: ValidationResult
    normalized_at: datetime


async def normalize_notice(
    session: AsyncSession, notice_id: int
) -> NoticeNormalizationOutcome:
    """공고 하나를 실제 저장된 메타데이터 + OCR 텍스트로 정규화하고 결과를 저장한다.

    OCR 텍스트(notice_attachment.parsed_text)가 있으면 그걸 우선 쓴다. 없으면
    summary_text로 대체한다 — 첨부파일이 아예 없는 공고가 실제로 약 76%에
    달해서(docs/matching-pipeline.md 참고), OCR 텍스트만 요구하면 대다수
    공고를 정규화할 방법이 없어진다. summary_text만으로는 세부 자격요건까지
    정확히 못 뽑을 수 있지만, 그 한계는 validation_result의
    missing_required_fields로 드러나므로 정규화 자체를 막을 이유는 아니다
    (AI 매칭 스코어링처럼 이 결과 자체가 최종 판단에 쓰이는 건 아님).
    """
    row = await get_notice_detail(session, notice_id)
    if row is None:
        raise NoticeNotFoundForNormalizationError(
            f"notice_id {notice_id}를 찾을 수 없습니다."
        )
    notice, source_name, category_name = row

    attachments = await get_notice_attachments(session, notice_id)
    ocr_target = pick_ocr_target(attachments)

    raw_text: str | None = None
    file_name: str | None = None
    file_type: str | None = None
    if ocr_target is not None and ocr_target.parsed_text:
        raw_text = ocr_target.parsed_text
        file_name = ocr_target.file_name
        file_type = ocr_target.file_type
    elif notice.summary_text:
        raw_text = notice.summary_text

    if not raw_text:
        raise NoSourceTextForNormalizationError(
            "정규화에 쓸 원문이 없습니다(OCR 텍스트도 summary_text도 없음)."
        )

    prompt_text = build_notice_prompt_text(
        label="공고",
        metadata={
            "notice_id": str(notice_id),
            "title": notice.title or "",
            "source": source_name or "",
            "category": category_name or "",
            "status": notice.status or "",
            "application_start_date": str(notice.application_start_date or ""),
            "application_end_date": str(notice.application_end_date or ""),
            "file_name": file_name or "",
            "file_type": file_type or "",
        },
        raw_text=raw_text,
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    try:
        normalized = await normalize_notice_text(prompt_text)
    except AiNormalizationError as exc:
        await update_notice_normalization(
            session,
            notice_id,
            normalized_json=None,
            normalization_status="failed",
            normalization_error=str(exc),
            normalized_at=now,
        )
        await session.commit()
        raise

    normalized = enrich_normalized_notice(
        normalized,
        title=notice.title,
        source=source_name,
        category=category_name,
        status=notice.status,
        application_start_date=notice.application_start_date,
        application_end_date=notice.application_end_date,
        raw_text=raw_text,
    )
    validation_result = validate_normalized_notice(normalized, source_text=raw_text)

    await update_notice_normalization(
        session,
        notice_id,
        normalized_json=normalized.model_dump(mode="json"),
        normalization_status="completed",
        normalization_error=None,
        normalized_at=now,
    )
    await session.commit()

    return NoticeNormalizationOutcome(
        normalized=normalized, validation_result=validation_result, normalized_at=now
    )

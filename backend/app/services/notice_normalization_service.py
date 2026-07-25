"""
services/notice_normalization_service.py

실제 DB에 저장된 공고를 대상으로 정규화(app.ai.notice_normalizer.normalize_notice_text
호출)를 실행하고 결과를 Notice에 저장한다. app/api/notice_samples.py(로컬 샘플 JSON
기준 테스트용 엔드포인트)와 같은 보완 규칙을 notice_normalization_helpers에서
공유해서 쓴다 — 다른 점은 원문을 로컬 파일이 아니라 실제 공고 메타데이터 +
OCR 결과에서 가져온다는 것뿐이다.

공고 하나에 PDF/HWP/HWPX 첨부파일이 여러 개일 수 있는데, 파일명만으로 "진짜
공고문"을 하나 고르는 방식(notice_ocr_target.pick_ocr_target)은 새로운 파일명
패턴(안내서/지침/FAQ 등)에 계속 뚫려 AI팀 정규화 품질 저하로 이어졌다
(docs/normalization-quality-report.md). 그래서 이 정규화 흐름에서는 후보를
미리 하나로 좁히지 않고, PDF/HWP/HWPX 후보 전부(+summary_text)를 각각 OCR·
정규화해본 뒤 검증 결과가 가장 좋은 것을 채택한다(2026-07-13 결정 — 비용은
gpt-4o-mini 기준 후보당 0.1센트 미만이라 무시할 만함).
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.normalizer import AiNormalizationError
from app.ai.notice_normalizer import normalize_notice_text
from app.models.notice import NoticeAttachment
from app.repositories.notice_repository import (
    get_notice_attachments,
    get_notice_detail,
    set_attachment_parsed_text,
    update_notice_normalization,
)
from app.schemas.business_plan import ValidationResult
from app.schemas.notice_normalization import NormalizedNoticeSchema
from app.services.notice_attachment_download import download_and_extract_attachment
from app.services.notice_normalization_helpers import (
    build_notice_prompt_text,
    enrich_normalized_notice,
    score_validation_result,
)
from app.services.notice_ocr_target import OCR_TARGET_FILE_TYPES
from app.services.notice_service import validate_normalized_notice

logger = logging.getLogger(__name__)

# OpenAI 쪽은 CLOVA(clova_ocr_client._clova_call_semaphore, 실측으로 5개 확인)와
# 달리 계정 전체 동시 호출 한도가 실측된 적은 없다. 하지만 배치 트리거(공고
# 최대 30건 동시) × 후보 전부 동시 정규화(옵션4)가 겹치면 실제 동시 OpenAI
# 호출이 100건을 넘을 수 있고, 이 상태에서 사업계획서 정규화가 문서 길이와
# 무관하게 30초 타임아웃을 3회 연속 채우고 실패하는 것을 실측함(2026-07-13,
# business_plan_id=207) — 이후 시간이 지나 재시도하니 정상 동작해, 그 시점에
# 동시 요청이 몰려 응답이 느려졌던 것으로 추정된다. CLOVA만큼 빡빡하게 5로
# 제한할 근거는 없어 계정 티어에 여유를 두고 10으로 둔다(이슈 #99).
_NOTICE_LLM_CONCURRENCY_LIMIT = 10
_notice_llm_semaphore = asyncio.Semaphore(_NOTICE_LLM_CONCURRENCY_LIMIT)


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


@dataclass
class _CandidateAttempt:
    file_name: str | None
    file_type: str | None
    raw_text: str
    normalized: NormalizedNoticeSchema
    validation_result: ValidationResult


async def _resolve_candidate_text(
    source_name: str, attachment: NoticeAttachment
) -> tuple[NoticeAttachment, str | None]:
    """후보 첨부파일의 텍스트를 확보한다(이미 있으면 재사용, 없으면 다운로드+OCR).

    다운로드·OCR은 후보마다 독립적인 외부 호출이라 DB 세션 없이 동시에
    실행할 수 있다(notice_ocr.py의 세션 분리와 같은 이유). 실패하면 이
    후보를 조용히 포기하도록 None을 반환한다 — 하나 실패해도 나머지
    후보로 계속 진행하기 위함.
    """
    if attachment.parsed_text is not None:
        return attachment, attachment.parsed_text

    try:
        text = await download_and_extract_attachment(source_name, attachment)
    except Exception:
        logger.exception(
            "정규화용 첨부파일 다운로드/OCR 실패 (attachment_id=%s)", attachment.id
        )
        return attachment, None
    return attachment, text


async def _try_normalize_candidate(
    *,
    notice_id: int,
    title: str | None,
    source_name: str | None,
    category_name: str | None,
    status_: str | None,
    application_start_date,
    application_end_date,
    file_name: str | None,
    file_type: str | None,
    raw_text: str,
) -> _CandidateAttempt | None:
    """후보 하나를 정규화해본다. LLM 호출 등 어떤 이유로든 실패하면 이 후보를
    포기하도록 None을 반환한다(하나 실패해도 나머지 후보 비교는 계속 진행)."""
    prompt_text = build_notice_prompt_text(
        label="공고",
        metadata={
            "notice_id": str(notice_id),
            "title": title or "",
            "source": source_name or "",
            "category": category_name or "",
            "status": status_ or "",
            "application_start_date": str(application_start_date or ""),
            "application_end_date": str(application_end_date or ""),
            "file_name": file_name or "",
            "file_type": file_type or "",
        },
        raw_text=raw_text,
    )
    try:
        async with _notice_llm_semaphore:
            normalized = await normalize_notice_text(prompt_text)
    except Exception:
        logger.exception(
            "공고 정규화 후보 시도 실패 (notice_id=%s, file_name=%s)",
            notice_id,
            file_name,
        )
        return None

    normalized = enrich_normalized_notice(
        normalized,
        title=title,
        source=source_name,
        category=category_name,
        status=status_,
        application_start_date=application_start_date,
        application_end_date=application_end_date,
        raw_text=raw_text,
    )
    validation_result = validate_normalized_notice(normalized, source_text=raw_text)
    return _CandidateAttempt(
        file_name=file_name,
        file_type=file_type,
        raw_text=raw_text,
        normalized=normalized,
        validation_result=validation_result,
    )


async def normalize_notice(
    session: AsyncSession, notice_id: int
) -> NoticeNormalizationOutcome:
    """공고 하나를 실제 저장된 메타데이터 + 첨부파일 원문으로 정규화하고 결과를 저장한다.

    PDF/HWP/HWPX 첨부파일 후보 전부(+summary_text)를 각각 정규화해보고,
    검증 결과(missing_required_fields+errors가 적을수록, is_valid=True 우선)가
    가장 좋은 것을 채택한다. 첨부파일이 아예 없는 공고가 실제로 약 76%에
    달해서(docs/matching-pipeline.md 참고) summary_text도 항상 후보에 포함한다.
    """
    row = await get_notice_detail(session, notice_id)
    if row is None:
        raise NoticeNotFoundForNormalizationError(
            f"notice_id {notice_id}를 찾을 수 없습니다."
        )
    notice, source_name, category_name = row
    # KgCategory.name은 CategoryName(str, Enum)으로 조회되는데, 그대로 두면
    # 직렬화 시 .value("자금") 대신 enum의 기본 __str__("CategoryName.FUND")가 나온다.
    category_name = category_name.value if category_name is not None else None

    attachments = await get_notice_attachments(session, notice_id)
    candidates = [a for a in attachments if a.file_type in OCR_TARGET_FILE_TYPES]

    # 1단계: 후보 텍스트 확보(다운로드·OCR은 서로 독립적이라 동시 실행).
    resolved = (
        await asyncio.gather(
            *(_resolve_candidate_text(source_name, a) for a in candidates)
        )
        if candidates
        else []
    )

    # 2단계: 새로 OCR한 결과만 저장(이미 있던 건 재저장 불필요). DB 쓰기는
    # 커넥션 풀 문제를 피하려고 여기서 순차적으로 짧게 끝낸다.
    text_candidates: list[tuple[str | None, str | None, str]] = []
    for attachment, text in resolved:
        if attachment.parsed_text is None and text is not None:
            await set_attachment_parsed_text(session, attachment.id, text)
        if text:
            text_candidates.append((attachment.file_name, attachment.file_type, text))
    if any(
        attachment.parsed_text is None and text is not None
        for attachment, text in resolved
    ):
        await session.commit()

    if notice.summary_text:
        text_candidates.append((None, None, notice.summary_text))

    if not text_candidates:
        # "failed"가 아니라 "skipped"로 구분한다 — LLM 호출이 아예 없었고(비용
        # 발생 없음), 재시도해도 원문이 생기지 않는 이상 해결되지 않는
        # 상태라 "고쳐야 할 실패"와 구분해야 한다(2026-07-14, 실측: 마감된
        # K-Startup 옛날 공고에 몰려있고 재시도로 해결 안 됨을 확인함).
        # 매칭 후보 조회(list_normalized_notice_candidates)는 completed만
        # 보므로 어느 쪽이든 매칭에는 영향 없다.
        error_message = "정규화에 쓸 원문이 없습니다(OCR 텍스트도 summary_text도 없음)."
        await update_notice_normalization(
            session,
            notice_id,
            normalized_json=None,
            normalization_status="skipped",
            normalization_error=error_message,
            normalized_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        await session.commit()
        raise NoSourceTextForNormalizationError(error_message)

    # 3단계: LLM 호출은 길면 수십 초(타임아웃 30초 × 재시도 3회)까지 걸리는
    # 외부 호출이라, 후보가 여러 개면 그만큼 오래 걸릴 수 있다 — 위 조회·쓰기가
    # 열어둔 트랜잭션(=DB 커넥션)을 커밋해 반납한 뒤에 실행한다(배치 트리거로
    # 여러 건이 동시에 돌 때 커넥션 풀이 고갈되는 것을 실제로 재현한 적 있음,
    # 2026-07-12). 후보끼리도 서로 독립적인 외부 호출이라 동시 실행한다.
    await session.commit()

    attempts = await asyncio.gather(
        *(
            _try_normalize_candidate(
                notice_id=notice_id,
                title=notice.title,
                source_name=source_name,
                category_name=category_name,
                status_=notice.status,
                application_start_date=notice.application_start_date,
                application_end_date=notice.application_end_date,
                file_name=file_name,
                file_type=file_type,
                raw_text=raw_text,
            )
            for file_name, file_type, raw_text in text_candidates
        )
    )
    successes = [attempt for attempt in attempts if attempt is not None]

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if not successes:
        error_message = (
            f"정규화 후보 {len(text_candidates)}건을 모두 시도했지만 전부 실패했습니다"
            "(LLM 호출 오류 등)."
        )
        await update_notice_normalization(
            session,
            notice_id,
            normalized_json=None,
            normalization_status="failed",
            normalization_error=error_message,
            normalized_at=now,
        )
        await session.commit()
        raise AiNormalizationError(error_message)

    winner = min(
        successes,
        key=lambda attempt: score_validation_result(attempt.validation_result),
    )

    saved = await update_notice_normalization(
        session,
        notice_id,
        normalized_json=winner.normalized.model_dump(mode="json"),
        normalization_status="completed",
        normalization_error=None,
        normalized_at=now,
    )
    await session.commit()

    if not saved:
        # 정규화(길면 후보 여러 개 × 수십 초)가 도는 동안 "기업마당 우선
        # 정책"으로 이 공고 자체가 삭제됐을 수 있다 — 실제로 재현함
        # (2026-07-12): 다른 트랜잭션이 delete_notice를 호출하면
        # update_notice_normalization이 0행을 반영하는데, 여기서 확인하지
        # 않으면 이미 사라진 공고에 대해 COMPLETED를 반환하게 된다.
        raise NoticeNotFoundForNormalizationError(
            "정규화는 끝났지만 공고가 더 이상 존재하지 않아 저장하지 못했습니다"
            "(다른 출처의 중복 공고로 정리됐을 수 있습니다)."
        )

    return NoticeNormalizationOutcome(
        normalized=winner.normalized,
        validation_result=winner.validation_result,
        normalized_at=now,
    )

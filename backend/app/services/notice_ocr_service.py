"""
services/notice_ocr_service.py

1차 필터링(품질·자격요건, matching_service._quality_errors/_eligibility_score)을
통과한 공고에 한해서만 첨부파일 OCR을 온디맨드로 수행한다 —
docs/matching-pipeline.md 4단계 원래 설계("1차로 좁혀진 공고에 한해서만
원문 PDF/HWP를 열어 정밀 분석")를 그대로 따른다.

app/api/notice_ocr.py(수동/배치 트리거, job 상태 추적 포함)와 다운로드·추출
로직은 같지만, 여기는 매칭 파이프라인(notice_embedding_service.ensure_notice_embedded)
안에서 공유 세션을 쓰며 조용히(잡 상태 없이) 호출되는 버전이다. 실패해도
예외를 던지지 않고 None을 반환한다 — 공고 하나의 OCR 실패로 전체 매칭이
중단되면 안 되기 때문(다른 후보는 계속 처리돼야 함).

커밋은 하지 않는다(flush만) — notice_embedding_service.ensure_notice_embedded와
동일하게 매칭 파이프라인의 공유 세션 안에서 호출되므로, 호출자(matching_service)가
트랜잭션 경계를 관리한다.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.kstartup_attachment_client import fetch_kstartup_attachments
from app.models.notice import NoticeAttachment
from app.repositories.notice_repository import (
    get_notice_attachments,
    get_notice_detail,
    save_attachment,
    set_attachment_parsed_text,
)
from app.services.notice_attachment_download import download_and_extract_attachment
from app.services.notice_collection_service import KSTARTUP_SOURCE_NAME
from app.services.notice_ocr_target import pick_ocr_target

logger = logging.getLogger(__name__)


def _file_type_from_name(file_name: str) -> str | None:
    if "." not in file_name:
        return None
    return file_name.rsplit(".", 1)[-1].upper()


async def ensure_notice_attachment_ocr(
    session: AsyncSession, notice_id: int
) -> NoticeAttachment | None:
    """공고의 OCR 대상 첨부파일(pick_ocr_target)에 parsed_text가 채워져
    있도록 보장하고 그 첨부파일 행을 반환한다.

    OCR 대상 자체가 없으면(첨부파일 없음/공고문으로 보이는 파일 없음/미지원
    포맷) None을 반환한다. K-Startup은 목록 API에 첨부파일 정보가 없어
    (app/api/notice_ocr.py와 동일한 이유) 첨부파일이 비어 있으면 상세페이지를
    먼저 크롤링한다.
    """
    row = await get_notice_detail(session, notice_id)
    if row is None:
        return None
    notice, source_name, _ = row

    try:
        attachments = await get_notice_attachments(session, notice_id)
    except Exception:
        logger.warning(
            "2차 필터링 온디맨드 OCR: 첨부파일 조회 실패 (notice_id=%s)",
            notice_id,
            exc_info=True,
        )
        return None

    if not attachments and source_name == KSTARTUP_SOURCE_NAME:
        try:
            fetched = await fetch_kstartup_attachments(int(notice.external_id))
        except Exception:
            logger.warning(
                "2차 필터링 온디맨드 OCR: K-Startup 첨부파일 크롤링 실패 "
                "(notice_id=%s)",
                notice_id,
                exc_info=True,
            )
            return None
        for file_name, file_url in fetched:
            await save_attachment(
                session,
                notice_id,
                file_name,
                file_url,
                _file_type_from_name(file_name),
            )
        attachments = await get_notice_attachments(session, notice_id)

    target = pick_ocr_target(attachments)
    if target is None:
        return None
    if target.parsed_text is not None:
        return target

    try:
        text = await download_and_extract_attachment(source_name, target)
    except Exception:
        logger.warning(
            "2차 필터링 온디맨드 OCR: 첨부파일 다운로드/OCR 실패 "
            "(notice_id=%s, attachment_id=%s)",
            notice_id,
            target.id,
            exc_info=True,
        )
        return None

    saved = await set_attachment_parsed_text(session, target.id, text)
    if not saved:
        # 다운로드·OCR이 도는 동안 "기업마당 우선 정책"으로 이 첨부파일의
        # 공고 자체가 지워졌을 수 있다(set_attachment_parsed_text 참고).
        return None

    target.parsed_text = text
    logger.info(
        "2차 필터링 온디맨드 OCR 완료 (notice_id=%s, attachment_id=%s): %d자",
        notice_id,
        target.id,
        len(text),
    )
    return target

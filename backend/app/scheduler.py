"""
scheduler.py

이슈 #102: 공고 수집·사전 OCR·정규화를 매일 새벽에 자동 실행한다(APScheduler,
main.py lifespan에서 시작). 흐름: 수집(전체 출처) -> 첨부파일 사전 OCR(전체
출처) -> 정규화 배치(전체 출처). 사전 OCR을 추가한 이유(2026-07-15): 온디맨드
방식이라 정규화/매칭 파이프라인 첫 요청이 느려졌다. 실패는 로그만 남기고
다음날 스케줄로 자연 복구한다.
"""

import logging
from typing import TYPE_CHECKING

from fastapi import BackgroundTasks

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 정규화 배치 API 자체 상한(30건, notice_normalization_job.py 참고)과 같은
# 이유 — 실수로 대량 요청이 들어가 OpenAI 비용이 한 번에 크게 나가는 것을
# 막기 위함. 스케줄러는 이 크기로 여러 번 나눠 돈다.
_NORMALIZATION_BATCH_SIZE = 30
# 하루 배치에서 처리할 최대 공고 수 상한. 밀린 공고가 아무리 많아도
# 하루치가 무한정 길어지지 않게 막는다 — 못 채운 나머지는 다음날 배치가
# 이어서 처리한다(정규화 안 된 공고는 계속 대상에 남아있으므로 유실 없음).
_DAILY_NORMALIZATION_LIMIT = 300
# 첨부파일 사전 OCR 하루 상한 — _DAILY_NORMALIZATION_LIMIT과 같은 이유(밀린
# 만큼 다음날 이어서 처리).
_DAILY_ATTACHMENT_OCR_LIMIT = 300


async def run_daily_notice_pipeline() -> None:
    """새벽 스케줄러가 호출하는 진입점. 수집 -> 첨부파일 사전 OCR -> 정규화 순서로 실행한다."""
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        await _run_collection(session)

    async with async_session_factory() as session:
        await _run_attachment_ocr_precollection(session)

    async with async_session_factory() as session:
        await _run_normalization_batch(session)


async def _run_collection(session: "AsyncSession") -> None:
    from app.services.notice_collection_service import (
        collect_all_bizinfo_notices,
        collect_all_kstartup_notices,
        collect_all_msit_notices,
    )

    try:
        # 기업마당을 먼저 수집해야 한다 — K-Startup을 먼저 수집하면 "기업마당
        # 우선 정책"으로 나중에 기업마당이 K-Startup 중복을 지울 때 이미
        # 받아둔 K-Startup 첨부파일까지 cascade로 같이 날아간다
        # (notice_collection_service.py 참고).
        bizinfo_result = await collect_all_bizinfo_notices(session)
        logger.info(
            "스케줄러: 기업마당 수집 완료 (성공 %d건, 실패 %d건)",
            bizinfo_result.saved_count,
            bizinfo_result.failed_count,
        )
    except Exception:
        logger.exception("스케줄러: 기업마당 수집 실패 — 정규화 단계는 계속 진행한다")

    try:
        kstartup_result = await collect_all_kstartup_notices(session)
        logger.info(
            "스케줄러: K-Startup 수집 완료 (성공 %d건, 실패 %d건)",
            kstartup_result.saved_count,
            kstartup_result.failed_count,
        )
    except Exception:
        logger.exception("스케줄러: K-Startup 수집 실패 — 정규화 단계는 계속 진행한다")

    try:
        # 기업마당/K-Startup의 "기업마당 우선" 중복 제거와 무관한 별도
        # 소스(R&D 카테고리 고정, 이슈 #104)라 순서 제약은 없다.
        msit_result = await collect_all_msit_notices(session)
        logger.info(
            "스케줄러: 과학기술정보통신부 수집 완료 (성공 %d건, 실패 %d건)",
            msit_result.saved_count,
            msit_result.failed_count,
        )
    except Exception:
        logger.exception(
            "스케줄러: 과학기술정보통신부 수집 실패 — 정규화 단계는 계속 진행한다"
        )


async def _run_attachment_ocr_precollection(session: "AsyncSession") -> None:
    """정규화 전에 기업마당/K-Startup 첨부파일을 미리 OCR해 parsed_text를 채운다.

    실제 다운로드·OCR은 precollect_notice_attachment_ocr이 기존 배치 트리거를 재사용한다.
    """
    from app.api.notice_attachment_precollection import (
        precollect_notice_attachment_ocr,
    )
    from app.schemas.notice_attachment_precollection import (
        NoticeAttachmentPrecollectRequest,
    )

    background_tasks = BackgroundTasks()
    try:
        result = await precollect_notice_attachment_ocr(
            background_tasks,
            request=NoticeAttachmentPrecollectRequest(limit=_DAILY_ATTACHMENT_OCR_LIMIT),
            session=session,
        )
        # 요청 컨텍스트가 없어 BackgroundTasks가 자동 실행되지 않으므로 직접 실행한다.
        await background_tasks()
    except Exception:
        logger.exception("스케줄러: 첨부파일 사전 OCR 트리거 실패")
        return

    if not result.notice_ids:
        logger.info("스케줄러: 첨부파일 사전 OCR 대상 공고 없음")
        return

    logger.info(
        "스케줄러: 첨부파일 사전 OCR 대상 %d건, 배치로 트리거 완료",
        len(result.notice_ids),
    )


async def _run_normalization_batch(session: "AsyncSession") -> None:
    from app.api.notice_normalization import start_notice_normalization_batch
    from app.repositories.notice_repository import (
        get_notice_ids_pending_normalization,
    )
    from app.schemas.notice_normalization_job import (
        NoticeNormalizationBatchTriggerRequest,
    )

    try:
        pending_ids = await get_notice_ids_pending_normalization(
            session, limit=_DAILY_NORMALIZATION_LIMIT
        )
    except Exception:
        logger.exception("스케줄러: 정규화 대상 조회 실패")
        return

    if not pending_ids:
        logger.info("스케줄러: 정규화 대상 공고 없음")
        return

    logger.info("스케줄러: 정규화 대상 %d건, 배치로 트리거 시작", len(pending_ids))

    for i in range(0, len(pending_ids), _NORMALIZATION_BATCH_SIZE):
        chunk = pending_ids[i : i + _NORMALIZATION_BATCH_SIZE]
        background_tasks = BackgroundTasks()
        try:
            await start_notice_normalization_batch(
                NoticeNormalizationBatchTriggerRequest(notice_ids=chunk),
                background_tasks,
            )
            # BackgroundTasks.add_task는 실제 HTTP 응답 이후 스타레트가
            # 실행해주는 구조라, 여기선 요청 컨텍스트가 없으므로 직접
            # 호출해서 실행한다.
            await background_tasks()
        except Exception:
            logger.exception(
                "스케줄러: 정규화 배치 청크 실패 (notice_ids=%s) — 다음 청크는 계속 진행",
                chunk,
            )

    logger.info("스케줄러: 정규화 배치 트리거 완료")

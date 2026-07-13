"""
scheduler.py

이슈 #102: 공고 수집·정규화를 매일 새벽에 자동 실행한다.
APScheduler를 FastAPI 앱 안에 내장하는 방식(app/main.py의 lifespan에서
시작/종료)을 쓴다 — 서버가 1대뿐이고 배포가 잦지 않은 지금 규모에서는
EC2 host crontab보다 git에 다 기록되는 이쪽이 관리하기 쉽다(2026-07-13
결정, crontab -l로 기존에 아무것도 없는 것 확인함).

흐름: 수집(기업마당 → K-Startup 순서 필수) → 아직 정규화를 시도한 적
없는 공고를 정규화 배치로 트리거. 첨부파일 OCR은 별도 배치를 안 거친다
— notice_normalization_service.normalize_notice(옵션4)가 후보마다
parsed_text 없으면 자기가 알아서 다운로드+OCR까지 하므로, 정규화 전에
OCR 배치를 따로 돌리는 건 중복 작업이다.

실패 처리는 이슈 #102에서 정한 대로 로그만 남기고(부분 실패는 각 단계
내부에서 이미 개별 격리돼 있음), 다음날 스케줄로 자연 복구한다 — 알림/
모니터링 대시보드는 지금 팀 규모에서는 범위 밖으로 뒀다.
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


async def run_daily_notice_pipeline() -> None:
    """새벽 스케줄러가 호출하는 진입점. 수집 -> 정규화 순서로 실행한다."""
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        await _run_collection(session)

    async with async_session_factory() as session:
        await _run_normalization_batch(session)


async def _run_collection(session: "AsyncSession") -> None:
    from app.services.notice_collection_service import (
        collect_all_bizinfo_notices,
        collect_all_kstartup_notices,
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

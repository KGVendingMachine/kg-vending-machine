"""
api/notice_normalization_backlog.py

공고 정규화 밀린 건 수동으로 한 번에 처리하는 라우터.
POST /internal/notices/normalize/backlog          -> 대상 전체 조회 + 일괄 트리거 (202 Accepted)
GET  /internal/notices/normalize/backlog/{job_id} -> 진행 상태 조회

스케줄러(scheduler.py)는 하루 최대 300건만 처리해 밀린 게 많으면 며칠 걸린다.
지금 당장 밀린 걸 처리하고 싶을 때 쓰는 수동 트리거 — 시작 시점에 대상
notice_id를 한 번에 고정해 목록으로 받고(중간에 재조회 안 함), 그 목록만
30건씩 순회한다. 재조회하지 않는 이유: failed/skipped도 재시도 대상이라
재조회하면 매번 같은 실패 건이 다시 뽑혀 목록이 줄어들지 않을 수 있다.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.notice_normalization import start_notice_normalization_batch
from app.db.session import get_db
from app.repositories.notice_repository import get_notice_ids_pending_normalization
from app.schemas.notice_normalization_backlog import (
    NormalizationBacklogJobAccepted,
    NormalizationBacklogJobStatus,
    NormalizationBacklogJobStatusResponse,
    NormalizationBacklogTriggerRequest,
)
from app.schemas.notice_normalization_job import NoticeNormalizationBatchTriggerRequest

router = APIRouter(prefix="/internal/notices", tags=["internal-notices"])

_JOBS: dict[str, NormalizationBacklogJobStatusResponse] = {}
_BATCH_CHUNK_SIZE = 30


def _has_active_backlog_job() -> bool:
    return any(
        job.status
        in (
            NormalizationBacklogJobStatus.PENDING,
            NormalizationBacklogJobStatus.RUNNING,
        )
        for job in _JOBS.values()
    )


async def _run_backlog_job(job_id: str, notice_ids: list[int]) -> None:
    _JOBS[job_id] = NormalizationBacklogJobStatusResponse(
        job_id=job_id,
        status=NormalizationBacklogJobStatus.RUNNING,
        total=len(notice_ids),
        processed=0,
    )
    try:
        for i in range(0, len(notice_ids), _BATCH_CHUNK_SIZE):
            chunk = notice_ids[i : i + _BATCH_CHUNK_SIZE]
            background_tasks = BackgroundTasks()
            await start_notice_normalization_batch(
                NoticeNormalizationBatchTriggerRequest(notice_ids=chunk),
                background_tasks,
            )
            # 요청 컨텍스트가 없어 BackgroundTasks가 자동 실행되지 않으므로 직접 실행한다.
            await background_tasks()
            _JOBS[job_id] = NormalizationBacklogJobStatusResponse(
                job_id=job_id,
                status=NormalizationBacklogJobStatus.RUNNING,
                total=len(notice_ids),
                processed=min(i + _BATCH_CHUNK_SIZE, len(notice_ids)),
            )
    except Exception as exc:
        current = _JOBS[job_id]
        _JOBS[job_id] = NormalizationBacklogJobStatusResponse(
            job_id=job_id,
            status=NormalizationBacklogJobStatus.FAILED,
            total=current.total,
            processed=current.processed,
            error_message=str(exc),
        )
        return

    _JOBS[job_id] = NormalizationBacklogJobStatusResponse(
        job_id=job_id,
        status=NormalizationBacklogJobStatus.COMPLETED,
        total=len(notice_ids),
        processed=len(notice_ids),
    )


@router.post(
    "/normalize/backlog",
    response_model=NormalizationBacklogJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="공고 정규화 밀린 건 일괄 시작",
    description=(
        "completed가 아닌 공고(신규 + 실패/스킵 재시도 대상)를 최대 limit개 "
        "찾아 30건씩 나눠 정규화를 트리거한다. 스케줄러의 하루 300건 제한 "
        "없이 지금 당장 밀린 걸 처리하고 싶을 때 쓴다."
    ),
)
async def start_normalization_backlog(
    background_tasks: BackgroundTasks,
    request: NormalizationBacklogTriggerRequest = NormalizationBacklogTriggerRequest(),
    session: AsyncSession = Depends(get_db),
):
    if _has_active_backlog_job():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 실행 중인 정규화 백로그 작업이 있습니다.",
        )

    notice_ids = await get_notice_ids_pending_normalization(
        session, limit=request.limit
    )

    job_id = str(uuid.uuid4())
    _JOBS[job_id] = NormalizationBacklogJobStatusResponse(
        job_id=job_id,
        status=NormalizationBacklogJobStatus.PENDING,
        total=len(notice_ids),
        processed=0,
    )
    background_tasks.add_task(_run_backlog_job, job_id, notice_ids)

    return NormalizationBacklogJobAccepted(job_id=job_id, total=len(notice_ids))


@router.get(
    "/normalize/backlog/{job_id}",
    response_model=NormalizationBacklogJobStatusResponse,
    summary="공고 정규화 백로그 작업 상태 조회",
)
async def get_normalization_backlog_status(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 job_id의 백로그 작업을 찾을 수 없습니다.",
        )
    return job

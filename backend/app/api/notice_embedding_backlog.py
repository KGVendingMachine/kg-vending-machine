"""
api/notice_embedding_backlog.py

공고 임베딩(2차 필터링) 밀린 건 수동으로 한 번에 처리하는 라우터.
POST /internal/notices/embed/backlog          -> 대상 전체 조회 + 일괄 트리거 (202 Accepted)
GET  /internal/notices/embed/backlog/{job_id} -> 진행 상태 조회

정규화 완료(completed)된 공고 전체를 대상으로 한다 — 원래 임베딩은 매칭
파이프라인이 1차 필터링 통과 후보에 대해서만 온디맨드로 하는 설계지만,
정규화 완료분 전체를 미리 임베딩해두고 싶을 때 쓰는 수동 트리거다. 이미
임베딩된 공고는 ensure_notice_embedded가 알아서 건너뛴다.

주의: Chroma는 PersistentClient(로컬 디스크)라 이 API를 실행한 프로세스가
돌아가는 서버의 디스크에 벡터가 저장된다 — 실제 배포 서버(EC2)에서
실행해야 매칭에 쓰인다.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.notice_embedding import start_notice_embedding_batch
from app.db.session import get_db
from app.repositories.notice_repository import get_notice_ids_completed_normalization
from app.schemas.notice_embedding import NoticeEmbeddingBatchTriggerRequest
from app.schemas.notice_embedding_backlog import (
    EmbeddingBacklogJobAccepted,
    EmbeddingBacklogJobStatus,
    EmbeddingBacklogJobStatusResponse,
    EmbeddingBacklogTriggerRequest,
)

router = APIRouter(prefix="/internal/notices", tags=["internal-notices"])

_JOBS: dict[str, EmbeddingBacklogJobStatusResponse] = {}
_BATCH_CHUNK_SIZE = 30


def _has_active_backlog_job() -> bool:
    return any(
        job.status
        in (EmbeddingBacklogJobStatus.PENDING, EmbeddingBacklogJobStatus.RUNNING)
        for job in _JOBS.values()
    )


async def _run_backlog_job(job_id: str, notice_ids: list[int]) -> None:
    _JOBS[job_id] = EmbeddingBacklogJobStatusResponse(
        job_id=job_id,
        status=EmbeddingBacklogJobStatus.RUNNING,
        total=len(notice_ids),
        processed=0,
    )
    try:
        for i in range(0, len(notice_ids), _BATCH_CHUNK_SIZE):
            chunk = notice_ids[i : i + _BATCH_CHUNK_SIZE]
            background_tasks = BackgroundTasks()
            await start_notice_embedding_batch(
                NoticeEmbeddingBatchTriggerRequest(notice_ids=chunk),
                background_tasks,
            )
            # 요청 컨텍스트가 없어 BackgroundTasks가 자동 실행되지 않으므로 직접 실행한다.
            await background_tasks()
            _JOBS[job_id] = EmbeddingBacklogJobStatusResponse(
                job_id=job_id,
                status=EmbeddingBacklogJobStatus.RUNNING,
                total=len(notice_ids),
                processed=min(i + _BATCH_CHUNK_SIZE, len(notice_ids)),
            )
    except Exception as exc:
        current = _JOBS[job_id]
        _JOBS[job_id] = EmbeddingBacklogJobStatusResponse(
            job_id=job_id,
            status=EmbeddingBacklogJobStatus.FAILED,
            total=current.total,
            processed=current.processed,
            error_message=str(exc),
        )
        return

    _JOBS[job_id] = EmbeddingBacklogJobStatusResponse(
        job_id=job_id,
        status=EmbeddingBacklogJobStatus.COMPLETED,
        total=len(notice_ids),
        processed=len(notice_ids),
    )


@router.post(
    "/embed/backlog",
    response_model=EmbeddingBacklogJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="공고 임베딩 밀린 건 일괄 시작",
    description=(
        "정규화 완료(completed)된 공고를 최대 limit개 찾아 30건씩 나눠 "
        "임베딩을 트리거한다. 이미 임베딩된 공고는 자동으로 건너뛴다."
    ),
)
async def start_embedding_backlog(
    background_tasks: BackgroundTasks,
    request: EmbeddingBacklogTriggerRequest = EmbeddingBacklogTriggerRequest(),
    session: AsyncSession = Depends(get_db),
):
    if _has_active_backlog_job():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 실행 중인 임베딩 백로그 작업이 있습니다.",
        )

    notice_ids = await get_notice_ids_completed_normalization(
        session, limit=request.limit
    )

    job_id = str(uuid.uuid4())
    _JOBS[job_id] = EmbeddingBacklogJobStatusResponse(
        job_id=job_id,
        status=EmbeddingBacklogJobStatus.PENDING,
        total=len(notice_ids),
        processed=0,
    )
    background_tasks.add_task(_run_backlog_job, job_id, notice_ids)

    return EmbeddingBacklogJobAccepted(job_id=job_id, total=len(notice_ids))


@router.get(
    "/embed/backlog/{job_id}",
    response_model=EmbeddingBacklogJobStatusResponse,
    summary="공고 임베딩 백로그 작업 상태 조회",
)
async def get_embedding_backlog_status(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 job_id의 백로그 작업을 찾을 수 없습니다.",
        )
    return job

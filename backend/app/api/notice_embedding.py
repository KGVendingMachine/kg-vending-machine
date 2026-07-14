"""
api/notice_embedding.py

공고 첨부파일 임베딩(2차 필터링) 트리거 라우터.
POST /internal/notices/{notice_id}/embed             -> 임베딩 작업 시작 (202 Accepted)
GET  /internal/notices/{notice_id}/embed/{job_id}    -> 작업 상태/결과 조회
POST /internal/notices/embed/batch                   -> 여러 공고 임베딩 작업 일괄 시작 (202 Accepted)
GET  /internal/notices/embed/batch/status            -> 배치 상태 일괄 조회

notice_ocr.py와 동일한 job-trigger/폴링 패턴(인메모리 _JOBS, 단건 409 충돌
방지, 배치는 세마포어로 동시 실행 수 제한)을 그대로 따른다.

매칭 파이프라인(secondary_filtering_service)은 이 API를 거치지 않고
services/notice_embedding_service.ensure_notice_embedded를 직접 호출한다 —
notice_normalization_service가 OCR을 트리거할 때 notice_ocr.py API를 거치지
않고 download_and_extract_attachment를 직접 부르는 것과 같은 이유다. 이
라우터는 운영진의 수동 트리거·사전 워밍업과 AI 팀 개발 검증용이다.
"""

import asyncio
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.ai.embedding_client import AiEmbeddingError
from app.db.session import async_session_factory
from app.repositories.notice_repository import get_notice_detail
from app.schemas.notice_embedding import (
    NoticeEmbeddingBatchJobItem,
    NoticeEmbeddingBatchStatusResponse,
    NoticeEmbeddingBatchTriggerRequest,
    NoticeEmbeddingBatchTriggerResponse,
    NoticeEmbeddingJobAccepted,
    NoticeEmbeddingJobStatus,
    NoticeEmbeddingJobStatusResponse,
)
from app.services.notice_embedding_service import ensure_notice_embedded

router = APIRouter(prefix="/internal/notices", tags=["internal-notices"])

_JOBS: dict[str, NoticeEmbeddingJobStatusResponse] = {}


async def _run_notice_embedding_job(job_id: str, notice_id: int) -> None:
    _JOBS[job_id] = NoticeEmbeddingJobStatusResponse(
        job_id=job_id, notice_id=notice_id, status=NoticeEmbeddingJobStatus.RUNNING
    )
    async with async_session_factory() as session:
        row = await get_notice_detail(session, notice_id)
        if row is None:
            _JOBS[job_id] = NoticeEmbeddingJobStatusResponse(
                job_id=job_id,
                notice_id=notice_id,
                status=NoticeEmbeddingJobStatus.FAILED,
                error_message="해당 id의 공고를 찾을 수 없습니다.",
            )
            return

        try:
            result = await ensure_notice_embedded(session, notice_id)
        except AiEmbeddingError as exc:
            _JOBS[job_id] = NoticeEmbeddingJobStatusResponse(
                job_id=job_id,
                notice_id=notice_id,
                status=NoticeEmbeddingJobStatus.FAILED,
                error_message=str(exc),
            )
            return
        await session.commit()

    if not result.embedded:
        _JOBS[job_id] = NoticeEmbeddingJobStatusResponse(
            job_id=job_id, notice_id=notice_id, status=NoticeEmbeddingJobStatus.NO_TEXT
        )
        return

    _JOBS[job_id] = NoticeEmbeddingJobStatusResponse(
        job_id=job_id,
        notice_id=notice_id,
        status=NoticeEmbeddingJobStatus.COMPLETED,
        chunk_count=result.chunk_count,
    )


async def _execute_notice_embedding_job(job_id: str, notice_id: int) -> None:
    try:
        await _run_notice_embedding_job(job_id, notice_id)
    except Exception as exc:
        _JOBS[job_id] = NoticeEmbeddingJobStatusResponse(
            job_id=job_id,
            notice_id=notice_id,
            status=NoticeEmbeddingJobStatus.FAILED,
            error_message=f"임베딩 작업 실행 실패: {exc}",
        )


def _active_job_for_notice(notice_id: int) -> NoticeEmbeddingJobStatusResponse | None:
    return next(
        (
            job
            for job in _JOBS.values()
            if job.notice_id == notice_id
            and job.status
            in (NoticeEmbeddingJobStatus.PENDING, NoticeEmbeddingJobStatus.RUNNING)
        ),
        None,
    )


def _has_active_job_for_notice(notice_id: int) -> bool:
    return _active_job_for_notice(notice_id) is not None


def _create_pending_job(notice_id: int) -> NoticeEmbeddingJobStatusResponse:
    job_id = str(uuid.uuid4())
    job = NoticeEmbeddingJobStatusResponse(
        job_id=job_id, notice_id=notice_id, status=NoticeEmbeddingJobStatus.PENDING
    )
    _JOBS[job_id] = job
    return job


def _start_notice_embedding_job(
    notice_id: int, background_tasks: BackgroundTasks
) -> NoticeEmbeddingJobStatusResponse:
    job = _create_pending_job(notice_id)
    background_tasks.add_task(_execute_notice_embedding_job, job.job_id, notice_id)
    return job


# 배치 안의 job을 전부 동시에 돌리면 OpenAI 임베딩 호출이 한꺼번에 몰릴 수
# 있어 notice_ocr.py의 _MAX_CONCURRENT_BATCH_OCR과 같은 이유로 제한한다.
_MAX_CONCURRENT_BATCH_EMBEDDING = 5


async def _run_batch_notice_embedding_jobs(
    job_notice_pairs: list[tuple[str, int]],
) -> None:
    """notice_ocr.py._run_batch_notice_ocr_jobs와 동일한 이유(FastAPI
    BackgroundTasks가 같은 응답의 task를 순서대로 하나씩 await하는 문제 회피)로
    세마포어로 직접 동시 실행한다."""
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_BATCH_EMBEDDING)

    async def _run_one(job_id: str, notice_id: int) -> None:
        async with semaphore:
            await _execute_notice_embedding_job(job_id, notice_id)

    await asyncio.gather(
        *(_run_one(job_id, notice_id) for job_id, notice_id in job_notice_pairs)
    )


@router.post(
    "/{notice_id}/embed",
    response_model=NoticeEmbeddingJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="공고 첨부파일 임베딩 시작 (2차 필터링)",
    description="공고 하나의 OCR 텍스트를 청크로 나눠 임베딩하고 벡터 DB에 적재한다.",
)
async def start_notice_embedding(notice_id: int, background_tasks: BackgroundTasks):
    if _has_active_job_for_notice(notice_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 이 공고에 대한 임베딩 작업이 진행 중입니다.",
        )

    job = _start_notice_embedding_job(notice_id, background_tasks)
    return NoticeEmbeddingJobAccepted(job_id=job.job_id, status=job.status)


@router.post(
    "/embed/batch",
    response_model=NoticeEmbeddingBatchTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="공고 첨부파일 임베딩 배치 시작 (2차 필터링)",
    description=(
        "여러 공고에 대해 한 번에 임베딩을 트리거한다. 이미 진행 중인 공고는 "
        "새로 시작하지 않고 기존 job을 그대로 반환한다."
    ),
)
async def start_notice_embedding_batch(
    request: NoticeEmbeddingBatchTriggerRequest, background_tasks: BackgroundTasks
):
    items = []
    new_jobs: list[tuple[str, int]] = []
    for notice_id in dict.fromkeys(request.notice_ids):
        existing = _active_job_for_notice(notice_id)
        if existing is not None:
            items.append(
                NoticeEmbeddingBatchJobItem(
                    notice_id=notice_id, job_id=existing.job_id, status=existing.status
                )
            )
            continue

        job = _create_pending_job(notice_id)
        new_jobs.append((job.job_id, notice_id))
        items.append(
            NoticeEmbeddingBatchJobItem(
                notice_id=notice_id, job_id=job.job_id, status=job.status
            )
        )

    if new_jobs:
        background_tasks.add_task(_run_batch_notice_embedding_jobs, new_jobs)
    return NoticeEmbeddingBatchTriggerResponse(items=items)


@router.get(
    "/embed/batch/status",
    response_model=NoticeEmbeddingBatchStatusResponse,
    summary="공고 첨부파일 임베딩 배치 상태 일괄 조회",
)
async def get_notice_embedding_batch_status(job_ids: list[str] = Query(default=[])):
    items = [_JOBS[job_id] for job_id in dict.fromkeys(job_ids) if job_id in _JOBS]
    return NoticeEmbeddingBatchStatusResponse(items=items)


@router.get(
    "/{notice_id}/embed/{job_id}",
    response_model=NoticeEmbeddingJobStatusResponse,
    summary="공고 첨부파일 임베딩 상태 조회",
)
async def get_notice_embedding_status(notice_id: int, job_id: str):
    job = _JOBS.get(job_id)
    if job is None or job.notice_id != notice_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 job_id의 임베딩 작업을 찾을 수 없습니다.",
        )
    return job

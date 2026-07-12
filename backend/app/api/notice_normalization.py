"""
api/notice_normalization.py

공고 정규화 트리거 라우터.
POST /internal/notices/{notice_id}/normalize          -> 정규화 작업 시작 (202 Accepted)
GET  /internal/notices/{notice_id}/normalize/{job_id}  -> 작업 상태/결과 조회
POST /internal/notices/normalize/batch                 -> 여러 공고 정규화 작업 일괄 시작 (202 Accepted)
GET  /internal/notices/normalize/batch/status          -> 배치 상태 일괄 조회

app/api/business_plan.py의 정규화 job 패턴(인메모리 _JOBS + BackgroundTasks)과
동일한 구조다. app/api/notice_samples.py(로컬 샘플 JSON 기준 테스트/검증용)와
달리, 이 API는 실제 DB에 저장된 공고(notice_id)를 대상으로 하고 결과를
Notice.normalized_json에 영속화해 job_id 없이도 나중에 조회할 수 있게 한다.

배치 트리거는 notice_ocr.py의 배치 OCR과 같은 이유로 만들었다 — 1차 필터링
통과 후보가 보통 여러 건이라, OCR 배치가 끝난 후보들을 한 번에 정규화하고
싶은 상황을 위함.
"""

import asyncio
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.normalizer import AiNormalizationError
from app.db.session import async_session_factory
from app.schemas.notice_normalization_job import (
    NoticeNormalizationBatchJobItem,
    NoticeNormalizationBatchStatusResponse,
    NoticeNormalizationBatchTriggerRequest,
    NoticeNormalizationBatchTriggerResponse,
    NoticeNormalizationJobAccepted,
    NoticeNormalizationJobStatus,
    NoticeNormalizationJobStatusResponse,
)
from app.services.notice_normalization_service import (
    NoticeNormalizationError,
    normalize_notice,
)

router = APIRouter(prefix="/internal/notices", tags=["internal-notices"])

_JOBS: dict[str, NoticeNormalizationJobStatusResponse] = {}


def _active_job_for_notice(
    notice_id: int,
) -> NoticeNormalizationJobStatusResponse | None:
    return next(
        (
            job
            for job in _JOBS.values()
            if job.notice_id == notice_id
            and job.status
            in (
                NoticeNormalizationJobStatus.PENDING,
                NoticeNormalizationJobStatus.RUNNING,
            )
        ),
        None,
    )


async def _run_normalization_job(
    session: AsyncSession, job_id: str, notice_id: int
) -> None:
    """정규화 실행 + _JOBS 상태 갱신. session 생명주기는 호출하는 쪽 책임."""
    try:
        outcome = await normalize_notice(session, notice_id)
    except (AiNormalizationError, NoticeNormalizationError) as exc:
        _JOBS[job_id] = NoticeNormalizationJobStatusResponse(
            notice_id=notice_id,
            job_id=job_id,
            status=NoticeNormalizationJobStatus.FAILED,
            error_message=str(exc),
        )
        return

    _JOBS[job_id] = NoticeNormalizationJobStatusResponse(
        notice_id=notice_id,
        job_id=job_id,
        status=NoticeNormalizationJobStatus.COMPLETED,
        normalized_json=outcome.normalized,
        validation_result=outcome.validation_result,
        normalized_at=outcome.normalized_at,
    )


async def _execute_normalization_job(job_id: str, notice_id: int) -> None:
    """BackgroundTasks 진입점. 요청 스코프 세션이 아니라 새 세션을 직접 연다
    (business_plan.py의 정규화 작업 실행기와 동일한 이유)."""
    async with async_session_factory() as session:
        await _run_normalization_job(session, job_id, notice_id)


def _create_pending_job(notice_id: int) -> NoticeNormalizationJobStatusResponse:
    """PENDING 상태의 job을 만들어 _JOBS에 등록한다 (백그라운드 실행은 등록하지
    않음). 단건/배치 트리거 둘 다 여기서 job을 만들고, 실행 방식(백그라운드
    태스크를 개별로 등록할지 묶어서 등록할지)만 호출자가 다르게 가져간다
    (notice_ocr.py의 _create_pending_job과 동일한 패턴)."""
    job_id = str(uuid.uuid4())
    job = NoticeNormalizationJobStatusResponse(
        notice_id=notice_id, job_id=job_id, status=NoticeNormalizationJobStatus.PENDING
    )
    _JOBS[job_id] = job
    return job


@router.post(
    "/{notice_id}/normalize",
    response_model=NoticeNormalizationJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="공고 정규화 시작",
    description=(
        "공고 하나를 실제 저장된 메타데이터 + OCR 텍스트로 정규화하는 작업을 "
        "백그라운드에서 시작한다. OCR 텍스트(notice_attachment.parsed_text)가 "
        "있으면 그걸 쓰고, 없으면 summary_text로 대체한다(첨부파일이 아예 없는 "
        "공고가 약 76%라 OCR 텍스트만 요구하면 대다수를 정규화할 방법이 없어짐). "
        "실패 사유(원문 없음/LLM 오류 등)는 상태 조회 응답의 error_message로 "
        "확인한다. 결과는 Notice.normalized_json에 저장돼 이후 job_id 없이도 "
        "조회할 수 있다."
    ),
)
async def start_notice_normalization(notice_id: int, background_tasks: BackgroundTasks):
    # 같은 공고에 동시에 두 번 트리거되면 OpenAI 호출이 이중으로 나간다
    # (notice_ocr.py의 CLOVA 이중 호출 방지와 같은 이유).
    existing = _active_job_for_notice(notice_id)
    if existing is not None:
        return NoticeNormalizationJobAccepted(
            notice_id=notice_id, job_id=existing.job_id, status=existing.status
        )

    job = _create_pending_job(notice_id)
    background_tasks.add_task(_execute_normalization_job, job.job_id, notice_id)

    return NoticeNormalizationJobAccepted(notice_id=notice_id, job_id=job.job_id)


@router.get(
    "/{notice_id}/normalize/{job_id}",
    response_model=NoticeNormalizationJobStatusResponse,
    summary="공고 정규화 상태 조회",
)
async def get_notice_normalization_status(notice_id: int, job_id: str):
    job = _JOBS.get(job_id)
    if job is None or job.notice_id != notice_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 job_id의 정규화 작업을 찾을 수 없습니다.",
        )
    return job


async def _run_batch_normalization_jobs(
    job_notice_pairs: list[tuple[str, int]],
) -> None:
    """배치로 새로 만든 job들을 동시에 실행한다.

    notice_ocr.py의 배치 OCR과 같은 이유로 BackgroundTasks에 하나씩 등록하지
    않고 여기서 직접 asyncio.gather로 동시 실행한다. CLOVA와 달리 OpenAI
    쪽은 계정 전체 동시 호출 개수 제한이 실측으로 확인된 적이 없어서(설정된
    OPENAI_MAX_RETRIES가 RateLimitError도 자체 재시도로 흡수함), 여기서는
    별도 세마포어 없이 최대 30건(요청 상한)을 그대로 동시 실행한다.
    """
    await asyncio.gather(
        *(
            _execute_normalization_job(job_id, notice_id)
            for job_id, notice_id in job_notice_pairs
        )
    )


@router.post(
    "/normalize/batch",
    response_model=NoticeNormalizationBatchTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="공고 정규화 배치 시작",
    description=(
        "여러 공고에 대해 한 번에 정규화를 트리거한다(OCR 배치 트리거와 동일한 "
        "이유 — 1차 필터링 후보가 보통 여러 건). 이미 진행 중인 공고는 새로 "
        "시작하지 않고 기존 job을 그대로 반환한다."
    ),
)
async def start_notice_normalization_batch(
    request: NoticeNormalizationBatchTriggerRequest, background_tasks: BackgroundTasks
):
    items = []
    new_jobs: list[tuple[str, int]] = []
    for notice_id in dict.fromkeys(request.notice_ids):  # 순서 유지하며 중복 제거
        existing = _active_job_for_notice(notice_id)
        if existing is not None:
            items.append(
                NoticeNormalizationBatchJobItem(
                    notice_id=notice_id, job_id=existing.job_id, status=existing.status
                )
            )
            continue

        job = _create_pending_job(notice_id)
        new_jobs.append((job.job_id, notice_id))
        items.append(
            NoticeNormalizationBatchJobItem(
                notice_id=notice_id, job_id=job.job_id, status=job.status
            )
        )

    if new_jobs:
        background_tasks.add_task(_run_batch_normalization_jobs, new_jobs)
    return NoticeNormalizationBatchTriggerResponse(items=items)


@router.get(
    "/normalize/batch/status",
    response_model=NoticeNormalizationBatchStatusResponse,
    summary="공고 정규화 배치 상태 일괄 조회",
    description=(
        "배치 트리거(POST /normalize/batch) 응답의 job_id 목록으로 진행 상태를 "
        "한 번에 조회한다. 존재하지 않는 job_id는 조용히 결과에서 빠진다(단건 "
        "조회의 404와 다름 — OCR 배치 상태 조회와 동일한 이유). job_ids를 아예 "
        "안 보내면 422 대신 빈 목록을 반환한다."
    ),
)
async def get_notice_normalization_batch_status(job_ids: list[str] = Query(default=[])):
    items = [_JOBS[job_id] for job_id in dict.fromkeys(job_ids) if job_id in _JOBS]
    return NoticeNormalizationBatchStatusResponse(items=items)

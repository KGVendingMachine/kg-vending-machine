"""
api/notice_normalization.py

공고 정규화 트리거 라우터.
POST /internal/notices/{notice_id}/normalize          -> 정규화 작업 시작 (202 Accepted)
GET  /internal/notices/{notice_id}/normalize/{job_id}  -> 작업 상태/결과 조회

app/api/business_plan.py의 정규화 job 패턴(인메모리 _JOBS + BackgroundTasks)과
동일한 구조다. app/api/notice_samples.py(로컬 샘플 JSON 기준 테스트/검증용)와
달리, 이 API는 실제 DB에 저장된 공고(notice_id)를 대상으로 하고 결과를
Notice.normalized_json에 영속화해 job_id 없이도 나중에 조회할 수 있게 한다.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.normalizer import AiNormalizationError
from app.db.session import async_session_factory
from app.schemas.notice_normalization_job import (
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

    job_id = str(uuid.uuid4())
    _JOBS[job_id] = NoticeNormalizationJobStatusResponse(
        notice_id=notice_id,
        job_id=job_id,
        status=NoticeNormalizationJobStatus.PENDING,
    )
    background_tasks.add_task(_execute_normalization_job, job_id, notice_id)

    return NoticeNormalizationJobAccepted(notice_id=notice_id, job_id=job_id)


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

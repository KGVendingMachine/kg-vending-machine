"""
api/notice_collection.py

공고 수집(기업마당/K-Startup) 트리거 라우터.
POST /internal/notices/collect              -> 수집 작업 시작 (202 Accepted)
GET  /internal/notices/collect/{job_id}      -> 작업 상태/결과 조회

작업 상태는 인메모리 딕셔너리(_JOBS)에 보관한다. 서버 재시작하면 사라지고
멀티 워커 환경에서는 워커마다 따로 관리됨 - 영속화는 추후 과제
(app/api/business_plan.py의 정규화 작업과 동일한 패턴/한계).

/internal prefix: 외부 사용자가 아니라 운영자가 트리거하는 내부 작업이라
docs/matching-pipeline.md 관례(관리자=/admin, 내부 모듈=/internal)를 따름.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.schemas.notice_collection import (
    CollectionJobAccepted,
    CollectionJobStatus,
    CollectionJobStatusResponse,
    SourceCollectionResult,
)
from app.services.notice_collection_service import (
    CollectionResult,
    collect_all_bizinfo_notices,
    collect_all_kstartup_notices,
)

router = APIRouter(prefix="/internal/notices", tags=["internal-notices"])

_JOBS: dict[str, CollectionJobStatusResponse] = {}


def _to_source_result(result: CollectionResult) -> SourceCollectionResult:
    return SourceCollectionResult(
        saved_count=result.saved_count,
        failed_count=result.failed_count,
        failed_ids=result.failed_ids,
    )


async def _run_collection_job(session: AsyncSession, job_id: str) -> None:
    """기업마당 → K-Startup 순서로 전체 수집을 실행하고 _JOBS 상태를 갱신한다.

    반드시 기업마당을 먼저 수집해야 한다 — K-Startup을 먼저 하면 "기업마당
    우선" 중복 제거 로직이 방금 크롤링한 K-Startup 첨부파일까지 지울 수
    있다 (docs/matching-pipeline.md 운영 규칙 참고).
    """
    _JOBS[job_id] = CollectionJobStatusResponse(
        job_id=job_id,
        status=CollectionJobStatus.RUNNING,
        current_phase="기업마당 수집 중",
    )
    try:
        bizinfo_result = await collect_all_bizinfo_notices(session)
    except Exception as exc:
        _JOBS[job_id] = CollectionJobStatusResponse(
            job_id=job_id,
            status=CollectionJobStatus.FAILED,
            error_message=f"기업마당 수집 실패: {exc}",
        )
        return

    _JOBS[job_id] = CollectionJobStatusResponse(
        job_id=job_id,
        status=CollectionJobStatus.RUNNING,
        current_phase="K-Startup 수집 중",
        bizinfo_result=_to_source_result(bizinfo_result),
    )
    try:
        kstartup_result = await collect_all_kstartup_notices(session)
    except Exception as exc:
        _JOBS[job_id] = CollectionJobStatusResponse(
            job_id=job_id,
            status=CollectionJobStatus.FAILED,
            bizinfo_result=_to_source_result(bizinfo_result),
            error_message=f"K-Startup 수집 실패: {exc}",
        )
        return

    _JOBS[job_id] = CollectionJobStatusResponse(
        job_id=job_id,
        status=CollectionJobStatus.COMPLETED,
        bizinfo_result=_to_source_result(bizinfo_result),
        kstartup_result=_to_source_result(kstartup_result),
    )


async def _execute_collection_job(job_id: str) -> None:
    """BackgroundTasks 진입점. 요청 스코프 세션이 아니라 새 세션을 직접 연다
    (business_plan.py의 정규화 작업 실행기와 동일한 이유)."""
    async with async_session_factory() as session:
        await _run_collection_job(session, job_id)


@router.post(
    "/collect",
    response_model=CollectionJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_collection(background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    _JOBS[job_id] = CollectionJobStatusResponse(
        job_id=job_id, status=CollectionJobStatus.PENDING
    )
    background_tasks.add_task(_execute_collection_job, job_id)

    return CollectionJobAccepted(job_id=job_id, status=CollectionJobStatus.PENDING)


@router.get("/collect/{job_id}", response_model=CollectionJobStatusResponse)
async def get_collection_status(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 job_id의 수집 작업을 찾을 수 없습니다.",
        )
    return job

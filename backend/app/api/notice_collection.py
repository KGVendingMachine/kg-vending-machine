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

스케줄러 연동 가이드 (실제 cron/APScheduler 배포는 별도 과제, 이슈 #49):
이 라우터의 API 자체는 스케줄러 없이도 완결돼 있어, 나중에 스케줄러가
붙을 때 아래 두 엔드포인트를 호출 순서만 지켜서 주기적으로 호출하면 된다.
- POST /internal/notices/collect: 기업마당 → K-Startup 순서가 코드
  내부(_run_collection_job)에 고정돼 있어 호출자가 순서를 신경 쓸 필요
  없다. 이미 실행 중이면 409를 반환하므로(_has_active_job), 스케줄러는
  409를 "건너뛰고 다음 주기에 재시도"로 처리하면 된다.
- POST /internal/notices/refresh-status: 순수하게 저장된 날짜만으로
  재계산·조건부 갱신만 하는 멱등 작업이라 별도 동시성 가드가 없어도
  언제, 몇 번을 호출해도 안전하다.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory, get_db
from app.schemas.notice_collection import (
    BizinfoRegionBackfillResult,
    CategoryBackfillResult,
    CollectionJobAccepted,
    CollectionJobStatus,
    CollectionJobStatusResponse,
    RegionCodeBackfillResult,
    SourceCollectionResult,
    StatusRefreshResult,
)
from app.services.notice_collection_service import (
    CollectionResult,
    backfill_bizinfo_nationwide_regions,
    backfill_notice_categories,
    backfill_notice_region_codes,
    collect_all_bizinfo_notices,
    collect_all_kstartup_notices,
    refresh_notice_statuses,
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
    (business_plan.py의 정규화 작업 실행기와 동일한 이유).

    세션을 여는 것 자체가 실패하는 경우까지 여기서 잡아야 한다 —
    _run_collection_job 안의 try/except는 그 함수 안에서 일어나는
    실패만 잡아서, 세션 생성 실패는 못 잡힌 채로 올라오면 job이
    PENDING에 영원히 멈추고 _has_active_job()이 계속 True를 반환해
    이후 수집 요청이 전부 막힌다.
    """
    try:
        async with async_session_factory() as session:
            await _run_collection_job(session, job_id)
    except Exception as exc:
        _JOBS[job_id] = CollectionJobStatusResponse(
            job_id=job_id,
            status=CollectionJobStatus.FAILED,
            error_message=f"수집 작업 실행 실패: {exc}",
        )


def _has_active_job() -> bool:
    return any(
        job.status in (CollectionJobStatus.PENDING, CollectionJobStatus.RUNNING)
        for job in _JOBS.values()
    )


@router.post(
    "/collect",
    response_model=CollectionJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="공고 수집 시작",
    description="기업마당 → K-Startup 순서로 공고 전체 수집을 백그라운드에서 시작한다.",
)
async def start_collection(background_tasks: BackgroundTasks):
    # 이미 도는 작업이 있는데 또 시작하면 K-Startup 첨부파일 크롤링까지
    # 겹쳐 돌아 외부 사이트에 요청이 배로 몰리고 리소스만 낭비한다.
    # (멀티 워커 환경에서는 워커별로 따로 관리되어 이 가드가 못 막는
    # 경우도 있음 — 모듈 docstring 참고.)
    if _has_active_job():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 실행 중인 공고 수집 작업이 있습니다.",
        )

    job_id = str(uuid.uuid4())
    _JOBS[job_id] = CollectionJobStatusResponse(
        job_id=job_id, status=CollectionJobStatus.PENDING
    )
    background_tasks.add_task(_execute_collection_job, job_id)

    return CollectionJobAccepted(job_id=job_id, status=CollectionJobStatus.PENDING)


@router.get(
    "/collect/{job_id}",
    response_model=CollectionJobStatusResponse,
    summary="공고 수집 상태 조회",
    description="진행 단계(current_phase)와 출처별 저장/실패 건수를 조회한다.",
)
async def get_collection_status(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 job_id의 수집 작업을 찾을 수 없습니다.",
        )
    return job


@router.post(
    "/backfill-category",
    response_model=CategoryBackfillResult,
    summary="기존 공고 category_id 보정",
    description=(
        "category_id 자동 매핑이 붙기 전에 저장돼 category_id가 비어있는 "
        "공고를 찾아, 이미 저장된 원본 응답(raw)만으로 다시 채운다. "
        "외부 API를 호출하지 않아 빠르게 끝나므로 동기로 처리한다."
    ),
)
async def backfill_category(session: AsyncSession = Depends(get_db)):
    result = await backfill_notice_categories(session)
    return CategoryBackfillResult(**result)


@router.post(
    "/refresh-status",
    response_model=StatusRefreshResult,
    summary="공고 모집 상태 갱신",
    description=(
        "마감일이 지났는데도 status가 예전 값(모집중/예정 등)으로 남아있는 "
        "공고를 오늘 날짜 기준으로 다시 계산해 마감 처리한다. 이미 저장된 "
        "날짜만으로 재계산하므로 외부 API를 호출하지 않는다. 추후 스케줄러가 "
        "주기적으로 호출하는 걸 염두에 두고 만든 API."
    ),
)
async def refresh_status(session: AsyncSession = Depends(get_db)):
    result = await refresh_notice_statuses(session)
    return StatusRefreshResult(**result)


@router.post(
    "/backfill-bizinfo-region",
    response_model=BizinfoRegionBackfillResult,
    summary="기업마당 전국 대상 공고 지역 보정",
    description=(
        "기업마당은 hashtags에 광역자치단체 17개를 전부 나열하는 방식으로 "
        "전국 대상을 표현한다. 전국 판정 로직이 추가되기 전에 저장된 공고에 "
        "region_code=ALL을 보정해 채운다. 이미 저장된 원본 응답(raw)만으로 "
        "재계산하므로 외부 API를 호출하지 않는다."
    ),
)
async def backfill_bizinfo_region(session: AsyncSession = Depends(get_db)):
    result = await backfill_bizinfo_nationwide_regions(session)
    return BizinfoRegionBackfillResult(**result)


@router.post(
    "/backfill-region-codes",
    response_model=RegionCodeBackfillResult,
    summary="공고 지역 코드 전체 보정",
    description=(
        "강원(51→42)/전북(52→45) 코드가 처음부터 잘못 저장돼 있던 것과, "
        "2026-07-01 전남·광주 통합으로 새로 생긴 '전남광주통합특별시' "
        "지역명을 반영해, 기업마당·K-Startup 공고 전체의 지역 코드를 "
        "저장된 원본(hashtags/supt_regin) 기준으로 재계산해 보정한다. "
        "외부 API를 다시 호출하지 않는다."
    ),
)
async def backfill_region_codes(session: AsyncSession = Depends(get_db)):
    result = await backfill_notice_region_codes(session)
    return RegionCodeBackfillResult(**result)

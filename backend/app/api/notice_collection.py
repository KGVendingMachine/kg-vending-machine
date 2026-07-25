"""
api/notice_collection.py

공고 수집(기업마당/K-Startup/과학기술정보통신부) 트리거 라우터.
POST /internal/notices/collect              -> 수집 작업 시작 (202 Accepted)
GET  /internal/notices/collect/{job_id}      -> 작업 상태/결과 조회

일회성 백필 API 3개는 운영 DB에서 이미 실행 완료해 제거함 — 서비스 함수와
단위 테스트는 로직 검증용으로 남겨둔다.

작업 상태는 인메모리 딕셔너리(_JOBS)에 보관한다. 서버 재시작하면 사라지고
멀티 워커 환경에서는 워커마다 따로 관리됨 - 영속화는 추후 과제
(app/api/business_plan.py의 정규화 작업과 동일한 패턴/한계).

/internal prefix: 외부 사용자가 아니라 운영자가 트리거하는 내부 작업이라
docs/matching-pipeline.md 관례(관리자=/admin, 내부 모듈=/internal)를 따름.

스케줄러 연동: 매일 새벽 3시(Asia/Seoul) 자동 실행되도록 app/scheduler.py에
연결돼 있다(이슈 #102, main.py lifespan에서 시작). 이 라우터의 API 자체는
스케줄러 없이도 완결돼 있어, 수동으로 트리거해도(Swagger 등) 동일하게 동작한다.
- POST /internal/notices/collect: 기업마당 → K-Startup → 과학기술정보통신부
  순서가 코드 내부(_run_collection_job)에 고정돼 있어 호출자가 순서를
  신경 쓸 필요 없다. 이미 실행 중이면 409를 반환하므로(_has_active_job),
  스케줄러는 409를 "건너뛰고 다음 주기에 재시도"로 처리한다.
- POST /internal/notices/refresh-status: 순수하게 저장된 날짜만으로
  재계산·조건부 갱신만 하는 멱등 작업이라 별도 동시성 가드가 없어도
  언제, 몇 번을 호출해도 안전하다.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory, get_db
from app.repositories.notice_repository import get_collection_stats
from app.schemas.notice_collection import (
    BusinessYearsBackfillResult,
    CollectionJobAccepted,
    CollectionJobStatus,
    CollectionJobStatusResponse,
    CollectionStatsResponse,
    NoticeRecollectionResult,
    SourceCollectionResult,
    StatusRefreshResult,
)
from app.services.notice_collection_service import (
    CollectionResult,
    NoticeRecollectionError,
    NoticeRecollectionNotFoundError,
    UnsupportedRecollectionSourceError,
    backfill_notice_business_years,
    collect_all_bizinfo_notices,
    collect_all_kstartup_notices,
    collect_all_msit_notices,
    recollect_bizinfo_notice,
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
    """기업마당 → K-Startup → 과학기술정보통신부 순서로 전체 수집을 실행하고
    _JOBS 상태를 갱신한다.

    반드시 기업마당을 먼저 수집해야 한다 — K-Startup을 먼저 하면 "기업마당
    우선" 중복 제거 로직이 방금 크롤링한 K-Startup 첨부파일까지 지울 수
    있다 (docs/matching-pipeline.md 운영 규칙 참고). 과학기술정보통신부는
    이 중복 제거 로직과 무관한 별도 소스(R&D 카테고리 고정)라 순서
    제약은 없지만, 진행 표시를 위해 세 번째 단계로 둔다.
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
        status=CollectionJobStatus.RUNNING,
        current_phase="과학기술정보통신부 수집 중",
        bizinfo_result=_to_source_result(bizinfo_result),
        kstartup_result=_to_source_result(kstartup_result),
    )
    try:
        msit_result = await collect_all_msit_notices(session)
    except Exception as exc:
        _JOBS[job_id] = CollectionJobStatusResponse(
            job_id=job_id,
            status=CollectionJobStatus.FAILED,
            bizinfo_result=_to_source_result(bizinfo_result),
            kstartup_result=_to_source_result(kstartup_result),
            error_message=f"과학기술정보통신부 수집 실패: {exc}",
        )
        return

    _JOBS[job_id] = CollectionJobStatusResponse(
        job_id=job_id,
        status=CollectionJobStatus.COMPLETED,
        bizinfo_result=_to_source_result(bizinfo_result),
        kstartup_result=_to_source_result(kstartup_result),
        msit_result=_to_source_result(msit_result),
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
    description=(
        "기업마당 → K-Startup → 과학기술정보통신부 순서로 공고 전체 수집을 "
        "백그라운드에서 시작한다."
    ),
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
    "/backfill-business-years",
    response_model=BusinessYearsBackfillResult,
    summary="공고 업력 구조화 컬럼 전체 보정",
    description=(
        "1차 필터의 업력 축을 위해 K-Startup 공고 전체의 biz_enyy를 저장된 "
        "원본 기준으로 다시 파싱해 target_business_years_max/"
        "target_allows_prestartup 컬럼을 채운다(해석 A: 누적 상한). "
        "컬럼 도입 이전에 수집된 공고를 소급 반영하는 용도이며 외부 API를 "
        "다시 호출하지 않는다."
    ),
)
async def backfill_business_years(session: AsyncSession = Depends(get_db)):
    result = await backfill_notice_business_years(session)
    return BusinessYearsBackfillResult(**result)


@router.post(
    "/{notice_id}/recollect",
    response_model=NoticeRecollectionResult,
    summary="공고 단건 재수집",
    description=(
        "이미 저장된 공고 하나만 원본 API에서 다시 가져와 갱신한다(마감일 "
        "연장, 첨부파일 교체 등 변경공고를 전체 재수집 없이 바로 반영하고 "
        "싶을 때 사용). 기업마당만 지원한다 — K-Startup 목록 API는 pbanc_sn "
        "필터를 줘도 조용히 무시하고 첫 페이지를 그대로 돌려줘(실제 호출로 "
        "확인함) 단건 조회 자체가 불가능하다."
    ),
)
async def recollect_notice(notice_id: int, session: AsyncSession = Depends(get_db)):
    try:
        await recollect_bizinfo_notice(session, notice_id)
    except NoticeRecollectionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except UnsupportedRecollectionSourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except NoticeRecollectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    return NoticeRecollectionResult(notice_id=notice_id)


@router.get(
    "/stats",
    response_model=CollectionStatsResponse,
    summary="공고 수집 현황 통계",
    description=(
        "출처/카테고리/상태별 저장 건수와 OCR 대기 건수를 집계한다. "
        "전부 이미 저장된 데이터에 대한 조회라 외부 API를 호출하지 않는다."
    ),
)
async def get_collection_stats_endpoint(session: AsyncSession = Depends(get_db)):
    stats = await get_collection_stats(session)
    return CollectionStatsResponse(**stats)

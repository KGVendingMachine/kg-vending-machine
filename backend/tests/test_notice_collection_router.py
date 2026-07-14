"""
tests/test_notice_collection_router.py

api/notice_collection.py 테스트. test_business_plan_router.py와 동일하게
실제 HTTP 서버 없이 라우터 함수를 직접 호출한다. 실제 백그라운드 실행
(_execute_collection_job)은 외부 크롤링 API를 부르므로 여기서는 스케줄링
여부와 _JOBS 상태 전이, 가드(409/404)만 검증한다.
"""

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api import notice_collection
from app.api.notice_collection import (
    _JOBS,
    _execute_collection_job,
    _run_collection_job,
    backfill_bizinfo_region,
    backfill_category,
    backfill_region_codes,
    get_collection_stats_endpoint,
    get_collection_status,
    recollect_notice,
    refresh_status,
    start_collection,
)
from app.schemas.notice_collection import (
    CollectionJobStatus,
    CollectionJobStatusResponse,
)
from app.services.notice_collection_service import (
    CollectionResult,
    NoticeRecollectionError,
    NoticeRecollectionNotFoundError,
    UnsupportedRecollectionSourceError,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def clear_jobs():
    _JOBS.clear()
    yield
    _JOBS.clear()


# ---------------------------------------------------------------------------
# start_collection
# ---------------------------------------------------------------------------


async def test_start_collection_returns_pending_and_schedules_task():
    background_tasks = BackgroundTasks()

    response = await start_collection(background_tasks)

    assert response.status == CollectionJobStatus.PENDING
    assert _JOBS[response.job_id].status == CollectionJobStatus.PENDING

    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is _execute_collection_job
    assert task.args == (response.job_id,)


async def test_start_collection_409_when_active_job_exists():
    _JOBS["existing"] = CollectionJobStatusResponse(
        job_id="existing", status=CollectionJobStatus.RUNNING
    )
    background_tasks = BackgroundTasks()

    with pytest.raises(HTTPException) as exc_info:
        await start_collection(background_tasks)

    assert exc_info.value.status_code == 409
    assert len(background_tasks.tasks) == 0


async def test_start_collection_allowed_when_previous_job_completed():
    _JOBS["finished"] = CollectionJobStatusResponse(
        job_id="finished", status=CollectionJobStatus.COMPLETED
    )
    background_tasks = BackgroundTasks()

    response = await start_collection(background_tasks)

    assert response.status == CollectionJobStatus.PENDING


async def test_run_collection_job_always_collects_bizinfo_before_kstartup(
    monkeypatch,
):
    """기업마당을 먼저 수집해야 하는 이유(K-Startup을 먼저 하면 "기업마당
    우선" 중복 제거 로직이 방금 크롤링한 K-Startup 첨부파일까지 지울 수 있음,
    docs/matching-pipeline.md 운영 규칙)가 코드 구조로 항상 지켜지는지
    회귀 테스트로 고정한다 (이슈 #49 — 스케줄러가 붙어도 호출 순서를
    신경 쓸 필요 없음을 보장)."""
    call_order = []

    async def fake_bizinfo(session):
        call_order.append("bizinfo")
        return CollectionResult(saved_count=1)

    async def fake_kstartup(session):
        call_order.append("kstartup")
        return CollectionResult(saved_count=2)

    async def fake_msit(session):
        call_order.append("msit")
        return CollectionResult(saved_count=3)

    monkeypatch.setattr(notice_collection, "collect_all_bizinfo_notices", fake_bizinfo)
    monkeypatch.setattr(
        notice_collection, "collect_all_kstartup_notices", fake_kstartup
    )
    monkeypatch.setattr(notice_collection, "collect_all_msit_notices", fake_msit)

    await _run_collection_job(session=object(), job_id="job-order")

    assert call_order == ["bizinfo", "kstartup", "msit"]
    assert _JOBS["job-order"].status == CollectionJobStatus.COMPLETED
    assert _JOBS["job-order"].msit_result.saved_count == 3


# ---------------------------------------------------------------------------
# get_collection_status
# ---------------------------------------------------------------------------


async def test_get_collection_status_returns_stored_job():
    stored = CollectionJobStatusResponse(
        job_id="job-1", status=CollectionJobStatus.RUNNING
    )
    _JOBS["job-1"] = stored

    result = await get_collection_status("job-1")

    assert result is stored


async def test_get_collection_status_404_when_unknown():
    with pytest.raises(HTTPException) as exc_info:
        await get_collection_status("unknown-job")

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# backfill_category
# ---------------------------------------------------------------------------


async def test_backfill_category_returns_checked_and_updated_counts(db_session):
    result = await backfill_category(session=db_session)

    assert result.checked >= 0
    assert result.updated >= 0
    assert result.updated <= result.checked


# ---------------------------------------------------------------------------
# refresh_status
# ---------------------------------------------------------------------------


async def test_refresh_status_returns_checked_and_updated_counts(db_session):
    result = await refresh_status(session=db_session)

    assert result.checked >= 0
    assert result.updated >= 0
    assert result.updated <= result.checked


# ---------------------------------------------------------------------------
# backfill_bizinfo_region
# ---------------------------------------------------------------------------


async def test_backfill_bizinfo_region_returns_checked_and_updated_counts(db_session):
    result = await backfill_bizinfo_region(session=db_session)

    assert result.checked >= 0
    assert result.updated >= 0
    assert result.updated <= result.checked


# ---------------------------------------------------------------------------
# backfill_region_codes
# ---------------------------------------------------------------------------


async def test_backfill_region_codes_returns_checked_and_updated_counts(db_session):
    result = await backfill_region_codes(session=db_session)

    assert result.checked >= 0
    assert result.updated >= 0
    assert result.updated <= result.checked


# ---------------------------------------------------------------------------
# recollect_notice
# ---------------------------------------------------------------------------


async def test_recollect_notice_returns_result_on_success(monkeypatch):
    async def fake_recollect(session, notice_id):
        assert notice_id == 42

    monkeypatch.setattr(notice_collection, "recollect_bizinfo_notice", fake_recollect)

    result = await recollect_notice(notice_id=42, session=object())

    assert result.notice_id == 42


async def test_recollect_notice_404_when_not_found(monkeypatch):
    async def fake_recollect(session, notice_id):
        raise NoticeRecollectionNotFoundError("찾을 수 없음")

    monkeypatch.setattr(notice_collection, "recollect_bizinfo_notice", fake_recollect)

    with pytest.raises(HTTPException) as exc_info:
        await recollect_notice(notice_id=999, session=object())

    assert exc_info.value.status_code == 404


async def test_recollect_notice_400_for_unsupported_source(monkeypatch):
    async def fake_recollect(session, notice_id):
        raise UnsupportedRecollectionSourceError("지원 안 함")

    monkeypatch.setattr(notice_collection, "recollect_bizinfo_notice", fake_recollect)

    with pytest.raises(HTTPException) as exc_info:
        await recollect_notice(notice_id=1, session=object())

    assert exc_info.value.status_code == 400


async def test_recollect_notice_502_for_generic_recollection_error(monkeypatch):
    async def fake_recollect(session, notice_id):
        raise NoticeRecollectionError("실패")

    monkeypatch.setattr(notice_collection, "recollect_bizinfo_notice", fake_recollect)

    with pytest.raises(HTTPException) as exc_info:
        await recollect_notice(notice_id=1, session=object())

    assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# get_collection_stats_endpoint
# ---------------------------------------------------------------------------


async def test_get_collection_stats_endpoint_returns_stats(db_session):
    result = await get_collection_stats_endpoint(session=db_session)

    assert result.ocr_pending_count >= 0
    assert isinstance(result.by_source, dict)
    assert isinstance(result.by_category, dict)
    assert isinstance(result.by_status, dict)
    assert isinstance(result.by_normalization_status, dict)

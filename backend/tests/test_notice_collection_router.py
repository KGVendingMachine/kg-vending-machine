"""
tests/test_notice_collection_router.py

api/notice_collection.py 테스트. test_business_plan_router.py와 동일하게
실제 HTTP 서버 없이 라우터 함수를 직접 호출한다. 실제 백그라운드 실행
(_execute_collection_job)은 외부 크롤링 API를 부르므로 여기서는 스케줄링
여부와 _JOBS 상태 전이, 가드(409/404)만 검증한다.
"""

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.notice_collection import (
    _JOBS,
    _execute_collection_job,
    backfill_category,
    get_collection_status,
    refresh_status,
    start_collection,
)
from app.schemas.notice_collection import CollectionJobStatus, CollectionJobStatusResponse

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


# ---------------------------------------------------------------------------
# get_collection_status
# ---------------------------------------------------------------------------


async def test_get_collection_status_returns_stored_job():
    stored = CollectionJobStatusResponse(job_id="job-1", status=CollectionJobStatus.RUNNING)
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

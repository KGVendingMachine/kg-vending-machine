"""
tests/test_notice_embedding_backlog_router.py

app/api/notice_embedding_backlog.py 테스트. 실제 임베딩(OpenAI/Chroma)은
호출하지 않고, start_notice_embedding_batch를 monkeypatch로 대체해 백로그
오케스트레이션 로직(30건 단위 청크 분할, job 상태 전이, 중복 실행 방지)만
검증한다.
"""

import uuid

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api import notice_embedding_backlog as backlog_router
from app.schemas.notice_embedding_backlog import (
    EmbeddingBacklogJobStatus,
    EmbeddingBacklogTriggerRequest,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _clear_jobs():
    backlog_router._JOBS.clear()
    yield
    backlog_router._JOBS.clear()


async def test_start_embedding_backlog_returns_pending_and_schedules_task(
    monkeypatch,
):
    async def fake_get_ids(session, *, limit):
        return [1, 2, 3]

    monkeypatch.setattr(
        backlog_router, "get_notice_ids_completed_normalization", fake_get_ids
    )

    background_tasks = BackgroundTasks()
    response = await backlog_router.start_embedding_backlog(
        background_tasks,
        EmbeddingBacklogTriggerRequest(),
        session=None,
    )

    assert response.status == EmbeddingBacklogJobStatus.PENDING
    assert response.total == 3
    assert backlog_router._JOBS[response.job_id].total == 3

    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is backlog_router._run_backlog_job
    assert task.args == (response.job_id, [1, 2, 3])


async def test_start_embedding_backlog_rejects_when_already_running():
    job_id = str(uuid.uuid4())
    backlog_router._JOBS[job_id] = backlog_router.EmbeddingBacklogJobStatusResponse(
        job_id=job_id,
        status=EmbeddingBacklogJobStatus.RUNNING,
        total=10,
        processed=3,
    )

    with pytest.raises(HTTPException) as exc_info:
        await backlog_router.start_embedding_backlog(
            BackgroundTasks(),
            EmbeddingBacklogTriggerRequest(),
            session=None,
        )

    assert exc_info.value.status_code == 409


async def test_run_backlog_job_completes_across_chunks(monkeypatch):
    call_log: list[list[int]] = []

    async def fake_batch(request, background_tasks):
        call_log.append(list(request.notice_ids))

    monkeypatch.setattr(backlog_router, "start_notice_embedding_batch", fake_batch)

    notice_ids = list(range(1, 65))  # 30건씩 3청크(30/30/4)로 나뉘어야 함
    job_id = str(uuid.uuid4())
    await backlog_router._run_backlog_job(job_id, notice_ids)

    job = backlog_router._JOBS[job_id]
    assert job.status == EmbeddingBacklogJobStatus.COMPLETED
    assert job.total == 64
    assert job.processed == 64
    assert [len(chunk) for chunk in call_log] == [30, 30, 4]


async def test_run_backlog_job_marks_failed_on_error(monkeypatch):
    async def fake_batch_failing(request, background_tasks):
        raise RuntimeError("임베딩 배치 호출 실패")

    monkeypatch.setattr(
        backlog_router, "start_notice_embedding_batch", fake_batch_failing
    )

    job_id = str(uuid.uuid4())
    await backlog_router._run_backlog_job(job_id, [1, 2, 3])

    job = backlog_router._JOBS[job_id]
    assert job.status == EmbeddingBacklogJobStatus.FAILED
    assert "임베딩 배치 호출 실패" in job.error_message


async def test_get_embedding_backlog_status_404_for_unknown_job():
    with pytest.raises(HTTPException) as exc_info:
        await backlog_router.get_embedding_backlog_status("존재하지-않는-job-id")

    assert exc_info.value.status_code == 404

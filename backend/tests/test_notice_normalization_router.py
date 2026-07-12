"""
tests/test_notice_normalization_router.py

api/notice_normalization.py 테스트. app/api/business_plan.py의 정규화 job
테스트(test_business_plan_router.py)와 동일한 구조다.

- _run_normalization_job: session을 파라미터로 받으므로 db_session 픽스처로 직접 검증.
- start_notice_normalization/get_notice_normalization_status: _JOBS 딕셔너리
  상태와 BackgroundTasks 스케줄링 여부만 확인한다. 실제 백그라운드 실행
  (_execute_normalization_job)은 자체 DB 커넥션을 새로 열기 때문에 여기서는
  실행하지 않는다.
"""

import uuid

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.ai.normalizer import AiNormalizationError
from app.api.notice_normalization import (
    _JOBS,
    _execute_normalization_job,
    _run_batch_normalization_jobs,
    _run_normalization_job,
    get_notice_normalization_batch_status,
    get_notice_normalization_result,
    get_notice_normalization_status,
    start_notice_normalization,
    start_notice_normalization_batch,
)
from app.models.notice_source import NoticeSource
from app.repositories.notice_repository import upsert_notice
from app.schemas.notice_normalization import NoticeBasicInfo, NormalizedNoticeSchema
from app.schemas.notice_normalization_job import (
    NoticeNormalizationBatchTriggerRequest,
    NoticeNormalizationJobStatus,
    NoticeNormalizationJobStatusResponse,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def clear_jobs():
    _JOBS.clear()
    yield
    _JOBS.clear()


async def _create_source(db_session, name: str) -> NoticeSource:
    source = NoticeSource(source_name=name, base_url="https://example.com")
    db_session.add(source)
    await db_session.flush()
    return source


async def _create_notice(db_session, source: NoticeSource, **overrides) -> int:
    defaults = dict(
        source_id=source.id,
        external_id="norm-router-1",
        title="테스트 공고",
        application_start_date=None,
        application_end_date=None,
        status="모집중",
        is_actionable=True,
        source_url=None,
        apply_url=None,
        summary_text="요약문",
    )
    defaults.update(overrides)
    return await upsert_notice(db_session, **defaults)


def _complete_normalized() -> NormalizedNoticeSchema:
    return NormalizedNoticeSchema(basic=NoticeBasicInfo(title="정규화된 제목"))


async def test_run_normalization_job_completes_and_stores_result(
    db_session, monkeypatch
):
    source = await _create_source(db_session, "라우터정규화테스트출처1")
    notice_id = await _create_notice(db_session, source, external_id="router-1")

    async def fake_normalize(prompt_text: str) -> NormalizedNoticeSchema:
        return _complete_normalized()

    monkeypatch.setattr(
        "app.services.notice_normalization_service.normalize_notice_text",
        fake_normalize,
    )

    job_id = str(uuid.uuid4())
    await _run_normalization_job(db_session, job_id, notice_id)

    job = _JOBS[job_id]
    assert job.status == NoticeNormalizationJobStatus.COMPLETED
    assert job.normalized_json.basic.title == "정규화된 제목"


async def test_run_normalization_job_fails_when_notice_missing(db_session):
    job_id = str(uuid.uuid4())
    await _run_normalization_job(db_session, job_id, 999_999_999)

    job = _JOBS[job_id]
    assert job.status == NoticeNormalizationJobStatus.FAILED
    assert "찾을 수 없습니다" in job.error_message


async def test_run_normalization_job_fails_when_ai_normalization_errors(
    db_session, monkeypatch
):
    source = await _create_source(db_session, "라우터정규화테스트출처2")
    notice_id = await _create_notice(db_session, source, external_id="router-2")

    async def fake_normalize_failing(prompt_text: str) -> NormalizedNoticeSchema:
        raise AiNormalizationError("LLM 호출 실패")

    monkeypatch.setattr(
        "app.services.notice_normalization_service.normalize_notice_text",
        fake_normalize_failing,
    )

    job_id = str(uuid.uuid4())
    await _run_normalization_job(db_session, job_id, notice_id)

    job = _JOBS[job_id]
    assert job.status == NoticeNormalizationJobStatus.FAILED
    assert job.error_message == "LLM 호출 실패"


async def test_start_notice_normalization_returns_pending_and_schedules_task():
    background_tasks = BackgroundTasks()

    response = await start_notice_normalization(
        notice_id=42, background_tasks=background_tasks
    )

    assert response.notice_id == 42
    assert response.status == NoticeNormalizationJobStatus.PENDING
    assert _JOBS[response.job_id].status == NoticeNormalizationJobStatus.PENDING

    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is _execute_normalization_job
    assert task.args == (response.job_id, 42)


async def test_start_notice_normalization_returns_existing_job_when_active():
    """같은 공고에 동시에 두 번 트리거되면 OpenAI 호출이 이중으로 나가므로,
    이미 진행 중인 job이 있으면 새로 시작하지 않고 그대로 반환해야 한다."""
    _JOBS["existing"] = NoticeNormalizationJobStatusResponse(
        notice_id=42, job_id="existing", status=NoticeNormalizationJobStatus.RUNNING
    )
    background_tasks = BackgroundTasks()

    response = await start_notice_normalization(
        notice_id=42, background_tasks=background_tasks
    )

    assert response.job_id == "existing"
    assert len(background_tasks.tasks) == 0


async def test_start_notice_normalization_starts_new_job_for_different_notice():
    _JOBS["existing"] = NoticeNormalizationJobStatusResponse(
        notice_id=42, job_id="existing", status=NoticeNormalizationJobStatus.RUNNING
    )
    background_tasks = BackgroundTasks()

    response = await start_notice_normalization(
        notice_id=43, background_tasks=background_tasks
    )

    assert response.job_id != "existing"
    assert len(background_tasks.tasks) == 1


async def test_start_notice_normalization_allowed_when_previous_job_completed():
    _JOBS["finished"] = NoticeNormalizationJobStatusResponse(
        notice_id=42, job_id="finished", status=NoticeNormalizationJobStatus.COMPLETED
    )
    background_tasks = BackgroundTasks()

    response = await start_notice_normalization(
        notice_id=42, background_tasks=background_tasks
    )

    assert response.status == NoticeNormalizationJobStatus.PENDING
    assert response.job_id != "finished"


async def test_get_notice_normalization_status_returns_stored_job():
    job_id = str(uuid.uuid4())
    stored = NoticeNormalizationJobStatusResponse(
        notice_id=1, job_id=job_id, status=NoticeNormalizationJobStatus.COMPLETED
    )
    _JOBS[job_id] = stored

    result = await get_notice_normalization_status(notice_id=1, job_id=job_id)

    assert result is stored


async def test_get_notice_normalization_status_404_when_job_id_unknown():
    with pytest.raises(HTTPException) as exc_info:
        await get_notice_normalization_status(notice_id=1, job_id="unknown")

    assert exc_info.value.status_code == 404


async def test_get_notice_normalization_status_404_when_notice_id_mismatch():
    job_id = str(uuid.uuid4())
    _JOBS[job_id] = NoticeNormalizationJobStatusResponse(
        notice_id=1, job_id=job_id, status=NoticeNormalizationJobStatus.COMPLETED
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_notice_normalization_status(notice_id=2, job_id=job_id)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# start_notice_normalization_batch
# ---------------------------------------------------------------------------


async def test_start_notice_normalization_batch_starts_a_job_per_notice():
    background_tasks = BackgroundTasks()

    response = await start_notice_normalization_batch(
        NoticeNormalizationBatchTriggerRequest(notice_ids=[1, 2, 3]), background_tasks
    )

    assert [item.notice_id for item in response.items] == [1, 2, 3]
    assert all(
        item.status == NoticeNormalizationJobStatus.PENDING for item in response.items
    )
    # 새 job들은 각자 background_tasks.add_task를 따로 부르지 않고 하나로
    # 묶여 동시 실행된다(OCR 배치와 동일한 이유 — _run_batch_normalization_jobs 참고).
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is _run_batch_normalization_jobs
    assert [notice_id for _, notice_id in task.args[0]] == [1, 2, 3]


async def test_start_notice_normalization_batch_dedupes_notice_ids():
    background_tasks = BackgroundTasks()

    response = await start_notice_normalization_batch(
        NoticeNormalizationBatchTriggerRequest(notice_ids=[1, 1, 2]), background_tasks
    )

    assert [item.notice_id for item in response.items] == [1, 2]
    assert len(background_tasks.tasks) == 1
    assert len(background_tasks.tasks[0].args[0]) == 2


async def test_start_notice_normalization_batch_reuses_existing_active_job():
    _JOBS["existing"] = NoticeNormalizationJobStatusResponse(
        job_id="existing", notice_id=1, status=NoticeNormalizationJobStatus.RUNNING
    )
    background_tasks = BackgroundTasks()

    response = await start_notice_normalization_batch(
        NoticeNormalizationBatchTriggerRequest(notice_ids=[1, 2]), background_tasks
    )

    reused, new = response.items
    assert reused.job_id == "existing"
    assert reused.status == NoticeNormalizationJobStatus.RUNNING
    assert new.notice_id == 2
    # 이미 진행 중인 공고는 새로 트리거하지 않으므로 신규 공고 1건만 배치에 포함됨
    assert len(background_tasks.tasks) == 1
    assert [notice_id for _, notice_id in background_tasks.tasks[0].args[0]] == [2]


async def test_start_notice_normalization_batch_schedules_no_task_when_all_active():
    _JOBS["existing"] = NoticeNormalizationJobStatusResponse(
        job_id="existing", notice_id=1, status=NoticeNormalizationJobStatus.RUNNING
    )
    background_tasks = BackgroundTasks()

    response = await start_notice_normalization_batch(
        NoticeNormalizationBatchTriggerRequest(notice_ids=[1]), background_tasks
    )

    assert response.items[0].job_id == "existing"
    assert len(background_tasks.tasks) == 0


# ---------------------------------------------------------------------------
# get_notice_normalization_batch_status
# ---------------------------------------------------------------------------


async def test_get_notice_normalization_batch_status_returns_requested_jobs_in_order():
    _JOBS["job-a"] = NoticeNormalizationJobStatusResponse(
        job_id="job-a", notice_id=1, status=NoticeNormalizationJobStatus.COMPLETED
    )
    _JOBS["job-b"] = NoticeNormalizationJobStatusResponse(
        job_id="job-b", notice_id=2, status=NoticeNormalizationJobStatus.RUNNING
    )

    response = await get_notice_normalization_batch_status(job_ids=["job-a", "job-b"])

    assert [item.job_id for item in response.items] == ["job-a", "job-b"]
    assert response.items[0].status == NoticeNormalizationJobStatus.COMPLETED
    assert response.items[1].status == NoticeNormalizationJobStatus.RUNNING


async def test_get_notice_normalization_batch_status_dedupes_duplicate_job_ids():
    _JOBS["job-a"] = NoticeNormalizationJobStatusResponse(
        job_id="job-a", notice_id=1, status=NoticeNormalizationJobStatus.COMPLETED
    )

    response = await get_notice_normalization_batch_status(job_ids=["job-a", "job-a"])

    assert [item.job_id for item in response.items] == ["job-a"]


async def test_get_notice_normalization_batch_status_silently_skips_unknown_job_ids():
    _JOBS["job-a"] = NoticeNormalizationJobStatusResponse(
        job_id="job-a", notice_id=1, status=NoticeNormalizationJobStatus.COMPLETED
    )

    response = await get_notice_normalization_batch_status(
        job_ids=["job-a", "존재하지-않는-job"]
    )

    assert [item.job_id for item in response.items] == ["job-a"]


async def test_get_notice_normalization_batch_status_returns_empty_for_empty_input():
    response = await get_notice_normalization_batch_status(job_ids=[])

    assert response.items == []


def test_get_notice_normalization_batch_status_returns_200_when_job_ids_omitted():
    """실제 HTTP에서 job_ids를 아예 안 보낼 때 422가 나지 않는지는 FastAPI
    계층까지 거쳐야 드러나므로 TestClient로 확인한다 (OCR 배치 상태 조회의
    동일한 검증과 같은 이유)."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.get("/api/internal/notices/normalize/batch/status")

    assert response.status_code == 200
    assert response.json() == {"items": []}


# ---------------------------------------------------------------------------
# _execute_normalization_job (예상 못 한 예외 처리)
# ---------------------------------------------------------------------------


async def test_execute_normalization_job_marks_failed_on_unexpected_error(monkeypatch):
    """정규화 예외(AiNormalizationError 등) 외의 실패 — 커넥션 풀 고갈 등 —
    가 나도 job이 PENDING에 영원히 멈추면 안 된다. PENDING은 "진행 중"으로
    취급돼 그 공고의 재트리거까지 막기 때문(실제로 배치 20건 동시 실행 시
    풀 고갈 → 20건 전부 PENDING 고착을 재현함, 2026-07-12)."""

    def broken_session_factory():
        raise RuntimeError("커넥션 풀 고갈")

    monkeypatch.setattr(
        "app.api.notice_normalization.async_session_factory", broken_session_factory
    )

    job_id = str(uuid.uuid4())
    _JOBS[job_id] = NoticeNormalizationJobStatusResponse(
        notice_id=1, job_id=job_id, status=NoticeNormalizationJobStatus.PENDING
    )

    await _execute_normalization_job(job_id, 1)

    job = _JOBS[job_id]
    assert job.status == NoticeNormalizationJobStatus.FAILED
    assert "커넥션 풀 고갈" in job.error_message


# ---------------------------------------------------------------------------
# get_notice_normalization_result (저장된 결과 조회)
# ---------------------------------------------------------------------------


async def test_get_notice_normalization_result_returns_stored_result(db_session):
    from datetime import datetime

    from app.repositories.notice_repository import update_notice_normalization

    source = await _create_source(db_session, "저장결과조회출처1")
    notice_id = await _create_notice(db_session, source, external_id="stored-1")
    await update_notice_normalization(
        db_session,
        notice_id,
        normalized_json={"basic": {"title": "저장된 제목"}},
        normalization_status="completed",
        normalization_error=None,
        normalized_at=datetime.now(),
    )

    result = await get_notice_normalization_result(
        notice_id=notice_id, session=db_session
    )

    assert result.normalization_status == "completed"
    assert result.normalized_json.basic.title == "저장된 제목"
    assert result.normalized_at is not None


async def test_get_notice_normalization_result_null_when_never_normalized(db_session):
    source = await _create_source(db_session, "저장결과조회출처2")
    notice_id = await _create_notice(db_session, source, external_id="stored-2")

    result = await get_notice_normalization_result(
        notice_id=notice_id, session=db_session
    )

    assert result.normalization_status is None
    assert result.normalized_json is None


async def test_get_notice_normalization_result_404_for_unknown_notice(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await get_notice_normalization_result(notice_id=999_999_999, session=db_session)

    assert exc_info.value.status_code == 404

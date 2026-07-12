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
    _run_normalization_job,
    get_notice_normalization_status,
    start_notice_normalization,
)
from app.models.notice_source import NoticeSource
from app.repositories.notice_repository import upsert_notice
from app.schemas.notice_normalization import NoticeBasicInfo, NormalizedNoticeSchema
from app.schemas.notice_normalization_job import (
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

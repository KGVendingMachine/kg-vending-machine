"""
tests/test_business_plan_router.py

NRM-001: api/business_plan.py 테스트.
실제 HTTP 서버 없이 라우터 함수를 직접 호출한다.

- _run_normalization_job: session을 파라미터로 받으므로 db_session 픽스처로 직접 검증.
- create_normalization/get_normalization_status: _JOBS 딕셔너리 상태와
  BackgroundTasks 스케줄링 여부만 확인한다. 실제 백그라운드 실행(_execute_normalization_job)은
  자체 DB 커넥션을 새로 열기 때문에(async_session_factory) 테스트 트랜잭션과 분리되어
  있어 여기서는 실행하지 않는다.
"""

import uuid

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.business_plan import (
    _JOBS,
    _execute_normalization_job,
    _run_normalization_job,
    create_normalization,
    get_normalization_status,
)
from app.ai.normalizer import AiNormalizationError
from app.models.business_plan import BusinessPlan
from app.models.company import CompanyProfile
from app.schemas.business_plan import (
    JobStatus,
    NormalizedBusinessPlanSchema,
    NormalizeRequest,
    NormalizeStatusResponse,
    ProblemInfo,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def clear_jobs():
    _JOBS.clear()
    yield
    _JOBS.clear()


def _complete_normalized() -> NormalizedBusinessPlanSchema:
    return NormalizedBusinessPlanSchema(problem=ProblemInfo(background="배경"))


async def _create_business_plan(
    db_session, company_profile: CompanyProfile, **overrides
) -> BusinessPlan:
    defaults = dict(company_profile_id=company_profile.id, title="테스트 사업계획서")
    defaults.update(overrides)
    plan = BusinessPlan(**defaults)
    db_session.add(plan)
    await db_session.flush()
    return plan


async def test_run_normalization_job_completes_and_stores_result(
    db_session, test_company_profile, monkeypatch
):
    plan = await _create_business_plan(
        db_session, test_company_profile, raw_text="원문"
    )

    async def fake_normalize(text: str) -> NormalizedBusinessPlanSchema:
        return _complete_normalized()

    monkeypatch.setattr("app.api.business_plan.normalize_text", fake_normalize)

    job_id = str(uuid.uuid4())
    await _run_normalization_job(db_session, job_id, plan.id, None)

    job = _JOBS[job_id]
    assert job.status == JobStatus.COMPLETED
    assert job.normalized_json == _complete_normalized()
    assert job.validation_result.is_valid is False  # 다른 필수 필드는 비어있음


async def test_run_normalization_job_fails_when_plan_missing(db_session, monkeypatch):
    async def fake_normalize(text: str) -> NormalizedBusinessPlanSchema:
        raise AssertionError("business_plan이 없으면 호출되면 안 됨")

    monkeypatch.setattr("app.api.business_plan.normalize_text", fake_normalize)

    job_id = str(uuid.uuid4())
    await _run_normalization_job(db_session, job_id, 999_999, None)

    job = _JOBS[job_id]
    assert job.status == JobStatus.FAILED
    assert "999999" in job.error_message


async def test_run_normalization_job_fails_when_no_source_text(
    db_session, test_company_profile, monkeypatch
):
    plan = await _create_business_plan(db_session, test_company_profile, raw_text=None)

    async def fake_normalize(text: str) -> NormalizedBusinessPlanSchema:
        raise AssertionError("텍스트가 없으면 호출되면 안 됨")

    monkeypatch.setattr("app.api.business_plan.normalize_text", fake_normalize)

    job_id = str(uuid.uuid4())
    await _run_normalization_job(db_session, job_id, plan.id, None)

    job = _JOBS[job_id]
    assert job.status == JobStatus.FAILED


async def test_run_normalization_job_fails_when_ai_normalization_errors(
    db_session, test_company_profile, monkeypatch
):
    plan = await _create_business_plan(
        db_session, test_company_profile, raw_text="원문"
    )

    async def fake_normalize(text: str) -> NormalizedBusinessPlanSchema:
        raise AiNormalizationError("LLM 호출 실패")

    monkeypatch.setattr("app.api.business_plan.normalize_text", fake_normalize)

    job_id = str(uuid.uuid4())
    await _run_normalization_job(db_session, job_id, plan.id, None)

    job = _JOBS[job_id]
    assert job.status == JobStatus.FAILED
    assert job.error_message == "LLM 호출 실패"


async def test_create_normalization_returns_pending_and_schedules_task():
    background_tasks = BackgroundTasks()

    response = await create_normalization(
        business_plan_id=42, background_tasks=background_tasks, request=None
    )

    assert response.business_plan_id == 42
    assert response.status == JobStatus.PENDING
    assert _JOBS[response.job_id].status == JobStatus.PENDING

    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is _execute_normalization_job
    assert task.args == (response.job_id, 42, None)


async def test_create_normalization_passes_extracted_text_to_task():
    background_tasks = BackgroundTasks()

    response = await create_normalization(
        business_plan_id=42,
        background_tasks=background_tasks,
        request=NormalizeRequest(extracted_text="테스트 전용 원문"),
    )

    task = background_tasks.tasks[0]
    assert task.args == (response.job_id, 42, "테스트 전용 원문")


async def test_get_normalization_status_returns_stored_job():
    job_id = str(uuid.uuid4())
    stored = NormalizeStatusResponse(
        business_plan_id=1, job_id=job_id, status=JobStatus.COMPLETED
    )
    _JOBS[job_id] = stored

    result = await get_normalization_status(business_plan_id=1, job_id=job_id)

    assert result is stored


async def test_get_normalization_status_404_when_job_id_unknown():
    with pytest.raises(HTTPException) as exc_info:
        await get_normalization_status(business_plan_id=1, job_id="unknown")

    assert exc_info.value.status_code == 404


async def test_get_normalization_status_404_when_business_plan_id_mismatch():
    job_id = str(uuid.uuid4())
    _JOBS[job_id] = NormalizeStatusResponse(
        business_plan_id=1, job_id=job_id, status=JobStatus.COMPLETED
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_normalization_status(business_plan_id=2, job_id=job_id)

    assert exc_info.value.status_code == 404

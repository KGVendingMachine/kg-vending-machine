"""
tests/test_notice_ocr_router.py

api/notice_ocr.py의 순수 로직(_pick_ocr_target/_file_type_from_name)과
동시 트리거 가드(_has_active_job_for_notice)를 검증한다. 실제 다운로드/OCR
호출은 외부 네트워크가 필요해 여기서 다루지 않는다.
"""

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.notice_ocr import (
    _JOBS,
    _execute_notice_ocr_job,
    _file_type_from_name,
    _has_active_job_for_notice,
    _pick_ocr_target,
    get_notice_ocr_status,
    start_notice_ocr,
)
from app.models.notice import NoticeAttachment
from app.schemas.notice_ocr import NoticeOcrJobStatus, NoticeOcrJobStatusResponse

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def clear_jobs():
    _JOBS.clear()
    yield
    _JOBS.clear()


def _attachment(**overrides) -> NoticeAttachment:
    defaults = dict(
        id=1, notice_id=1, file_name="a.pdf", file_type="PDF", parsed_text=None
    )
    defaults.update(overrides)
    return NoticeAttachment(**defaults)


# ---------------------------------------------------------------------------
# _file_type_from_name
# ---------------------------------------------------------------------------


def test_file_type_from_name_uppercases_extension():
    assert _file_type_from_name("공고문.pdf") == "PDF"


def test_file_type_from_name_none_when_no_extension():
    assert _file_type_from_name("확장자없음") is None


# ---------------------------------------------------------------------------
# _pick_ocr_target
# ---------------------------------------------------------------------------


def test_pick_ocr_target_none_when_no_attachments():
    assert _pick_ocr_target([]) is None


def test_pick_ocr_target_none_when_only_non_document_types():
    attachments = [_attachment(file_type="HWP2")]  # OCR 대상 아닌 임의 포맷
    assert _pick_ocr_target(attachments) is None


def test_pick_ocr_target_prefers_already_parsed_over_first_match():
    unparsed = _attachment(id=1, file_type="PDF", parsed_text=None)
    parsed = _attachment(id=2, file_type="HWP", parsed_text="이미 뽑아둔 텍스트")

    result = _pick_ocr_target([unparsed, parsed])

    assert result.id == 2


def test_pick_ocr_target_falls_back_to_first_document_type_when_none_parsed():
    non_document = _attachment(id=1, file_type="ZIP")
    first_doc = _attachment(id=2, file_type="PDF")
    second_doc = _attachment(id=3, file_type="HWPX")

    result = _pick_ocr_target([non_document, first_doc, second_doc])

    assert result.id == 2


# ---------------------------------------------------------------------------
# _has_active_job_for_notice
# ---------------------------------------------------------------------------


def test_has_active_job_for_notice_true_when_running_job_exists():
    _JOBS["job-1"] = NoticeOcrJobStatusResponse(
        job_id="job-1", notice_id=42, status=NoticeOcrJobStatus.RUNNING
    )

    assert _has_active_job_for_notice(42) is True
    assert _has_active_job_for_notice(999) is False


def test_has_active_job_for_notice_false_when_job_completed():
    _JOBS["job-1"] = NoticeOcrJobStatusResponse(
        job_id="job-1", notice_id=42, status=NoticeOcrJobStatus.COMPLETED
    )

    assert _has_active_job_for_notice(42) is False


# ---------------------------------------------------------------------------
# start_notice_ocr
# ---------------------------------------------------------------------------


async def test_start_notice_ocr_returns_pending_and_schedules_task():
    background_tasks = BackgroundTasks()

    response = await start_notice_ocr(42, background_tasks)

    assert response.status == NoticeOcrJobStatus.PENDING
    assert _JOBS[response.job_id].notice_id == 42

    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is _execute_notice_ocr_job
    assert task.args == (response.job_id, 42)


async def test_start_notice_ocr_409_when_active_job_for_same_notice():
    _JOBS["existing"] = NoticeOcrJobStatusResponse(
        job_id="existing", notice_id=42, status=NoticeOcrJobStatus.RUNNING
    )
    background_tasks = BackgroundTasks()

    with pytest.raises(HTTPException) as exc_info:
        await start_notice_ocr(42, background_tasks)

    assert exc_info.value.status_code == 409
    assert len(background_tasks.tasks) == 0


async def test_start_notice_ocr_allowed_for_different_notice_while_one_running():
    _JOBS["existing"] = NoticeOcrJobStatusResponse(
        job_id="existing", notice_id=42, status=NoticeOcrJobStatus.RUNNING
    )
    background_tasks = BackgroundTasks()

    response = await start_notice_ocr(99, background_tasks)

    assert response.status == NoticeOcrJobStatus.PENDING


# ---------------------------------------------------------------------------
# get_notice_ocr_status
# ---------------------------------------------------------------------------


async def test_get_notice_ocr_status_returns_stored_job():
    stored = NoticeOcrJobStatusResponse(
        job_id="job-1", notice_id=42, status=NoticeOcrJobStatus.COMPLETED
    )
    _JOBS["job-1"] = stored

    result = await get_notice_ocr_status(42, "job-1")

    assert result is stored


async def test_get_notice_ocr_status_404_when_job_id_unknown():
    with pytest.raises(HTTPException) as exc_info:
        await get_notice_ocr_status(42, "unknown-job")

    assert exc_info.value.status_code == 404


async def test_get_notice_ocr_status_404_when_notice_id_mismatch():
    _JOBS["job-1"] = NoticeOcrJobStatusResponse(
        job_id="job-1", notice_id=42, status=NoticeOcrJobStatus.COMPLETED
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_notice_ocr_status(999, "job-1")

    assert exc_info.value.status_code == 404

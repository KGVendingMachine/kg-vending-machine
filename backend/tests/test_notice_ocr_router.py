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
    _run_batch_notice_ocr_jobs,
    get_notice_ocr_batch_status,
    get_notice_ocr_status,
    start_notice_ocr,
    start_notice_ocr_batch,
)
from app.models.notice import NoticeAttachment
from app.schemas.notice_ocr import (
    NoticeOcrBatchTriggerRequest,
    NoticeOcrJobStatus,
    NoticeOcrJobStatusResponse,
)

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


def test_pick_ocr_target_treats_empty_string_parsed_text_as_already_parsed():
    """parsed_text는 None(아직 처리 안 함)과 ""(처리했지만 텍스트가 없었음)을
    구분해야 한다 — truthy 체크를 쓰면 빈 문자열도 "아직"으로 오인해 계속
    재-OCR하게 된다."""
    unparsed = _attachment(id=1, file_type="PDF", parsed_text=None)
    parsed_empty = _attachment(id=2, file_type="HWP", parsed_text="")

    result = _pick_ocr_target([unparsed, parsed_empty])

    assert result.id == 2


def test_pick_ocr_target_falls_back_to_first_document_type_when_none_parsed():
    non_document = _attachment(id=1, file_type="ZIP")
    first_doc = _attachment(id=2, file_type="PDF")
    second_doc = _attachment(id=3, file_type="HWPX")

    result = _pick_ocr_target([non_document, first_doc, second_doc])

    assert result.id == 2


def test_pick_ocr_target_prefers_notice_document_name_over_attachment_forms():
    application_form = _attachment(
        id=1, file_type="HWP", file_name="붙임1. 신청서 및 사업계획서 서식.hwp"
    )
    notice_document = _attachment(
        id=2, file_type="PDF", file_name="26년_지원사업_추가_공고문.pdf"
    )

    result = _pick_ocr_target([application_form, notice_document])

    assert result.id == 2


def test_pick_ocr_target_matches_gongmo_keyword_too():
    application_form = _attachment(
        id=1, file_type="HWP", file_name="붙임1. 융자신청서.hwp"
    )
    notice_document = _attachment(
        id=2, file_type="PDF", file_name="[공모] 2026 예술산업보증 공모요강.pdf"
    )

    result = _pick_ocr_target([application_form, notice_document])

    assert result.id == 2


def test_pick_ocr_target_falls_back_when_no_name_looks_like_notice_document():
    first_doc = _attachment(id=1, file_type="PDF", file_name="a.pdf")
    second_doc = _attachment(id=2, file_type="HWPX", file_name="b.hwpx")

    result = _pick_ocr_target([first_doc, second_doc])

    assert result.id == 1


def test_pick_ocr_target_excludes_application_form_that_also_mentions_gongmo():
    """실제 DB(notice_id=11)에서 발견한 케이스: 신청서 파일명에도 "공모"가
    들어있어서 키워드만으로는 진짜 공고문과 구분이 안 됐다."""
    application_form = _attachment(
        id=21,
        file_type="HWP",
        file_name="붙임1. 2026 예술산업 금융지원 시범사업(융자) 3차 공모 융자신청서(2).hwp",
    )
    notice_document = _attachment(
        id=24,
        file_type="PDF",
        file_name="[공모] 2026 예술산업 금융지원 시범사업(융자) 3차 공모요강(변경).pdf",
    )

    result = _pick_ocr_target([application_form, notice_document])

    assert result.id == 24


def test_pick_ocr_target_excludes_application_form_that_also_mentions_gonggo():
    """실제 DB에서 발견한 또 다른 케이스: "신청서식(변경공고).hwp"처럼 신청
    양식 파일명에 "공고"가 포함된 경우."""
    application_form = _attachment(
        id=1,
        file_type="HWP",
        file_name="2026년 강원특별자치도 중소기업육성자금 신청서식(변경공고).hwp",
    )
    notice_document = _attachment(
        id=2,
        file_type="HWP",
        file_name="2026년 강원특별자치도 중소기업육성자금 지원 변경계획(3차) 공고문.hwp",
    )

    result = _pick_ocr_target([application_form, notice_document])

    assert result.id == 2


def test_pick_ocr_target_prefers_already_parsed_notice_document():
    unparsed_notice_doc = _attachment(
        id=1, file_type="PDF", file_name="공고문.pdf", parsed_text=None
    )
    parsed_form = _attachment(
        id=2,
        file_type="HWP",
        file_name="붙임. 신청서.hwp",
        parsed_text="이미 뽑아둔 텍스트",
    )

    result = _pick_ocr_target([unparsed_notice_doc, parsed_form])

    assert result.id == 1


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


# ---------------------------------------------------------------------------
# start_notice_ocr_batch
# ---------------------------------------------------------------------------


async def test_start_notice_ocr_batch_starts_a_job_per_notice():
    background_tasks = BackgroundTasks()

    response = await start_notice_ocr_batch(
        NoticeOcrBatchTriggerRequest(notice_ids=[1, 2, 3]), background_tasks
    )

    assert [item.notice_id for item in response.items] == [1, 2, 3]
    assert all(item.status == NoticeOcrJobStatus.PENDING for item in response.items)
    # 새 job들은 각자 background_tasks.add_task를 따로 부르지 않고 하나로
    # 묶여 동시 실행된다(순차 실행되면 가벼운 job이 무거운 job 뒤에서
    # 기다리게 되는 문제가 있었음 — _run_batch_notice_ocr_jobs 참고).
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is _run_batch_notice_ocr_jobs
    assert [notice_id for _, notice_id in task.args[0]] == [1, 2, 3]


async def test_start_notice_ocr_batch_dedupes_notice_ids():
    background_tasks = BackgroundTasks()

    response = await start_notice_ocr_batch(
        NoticeOcrBatchTriggerRequest(notice_ids=[1, 1, 2]), background_tasks
    )

    assert [item.notice_id for item in response.items] == [1, 2]
    assert len(background_tasks.tasks) == 1
    assert len(background_tasks.tasks[0].args[0]) == 2


async def test_start_notice_ocr_batch_reuses_existing_active_job_instead_of_409():
    _JOBS["existing"] = NoticeOcrJobStatusResponse(
        job_id="existing", notice_id=1, status=NoticeOcrJobStatus.RUNNING
    )
    background_tasks = BackgroundTasks()

    response = await start_notice_ocr_batch(
        NoticeOcrBatchTriggerRequest(notice_ids=[1, 2]), background_tasks
    )

    reused, new = response.items
    assert reused.job_id == "existing"
    assert reused.status == NoticeOcrJobStatus.RUNNING
    assert new.notice_id == 2
    # 이미 진행 중인 공고는 새로 트리거하지 않으므로 신규 공고 1건만 배치에 포함됨
    assert len(background_tasks.tasks) == 1
    assert [notice_id for _, notice_id in background_tasks.tasks[0].args[0]] == [2]


async def test_start_notice_ocr_batch_schedules_no_task_when_all_jobs_already_active():
    _JOBS["existing"] = NoticeOcrJobStatusResponse(
        job_id="existing", notice_id=1, status=NoticeOcrJobStatus.RUNNING
    )
    background_tasks = BackgroundTasks()

    response = await start_notice_ocr_batch(
        NoticeOcrBatchTriggerRequest(notice_ids=[1]), background_tasks
    )

    assert response.items[0].job_id == "existing"
    assert len(background_tasks.tasks) == 0


# ---------------------------------------------------------------------------
# get_notice_ocr_batch_status
# ---------------------------------------------------------------------------


async def test_get_notice_ocr_batch_status_returns_requested_jobs_in_order():
    """배치 트리거는 여러 건을 한 번에 시작할 수 있는데, 상태 확인은 건마다
    따로 해야 하는 비대칭이 있었다 — 이를 없애기 위한 일괄 조회."""
    _JOBS["job-a"] = NoticeOcrJobStatusResponse(
        job_id="job-a", notice_id=1, status=NoticeOcrJobStatus.COMPLETED, char_count=10
    )
    _JOBS["job-b"] = NoticeOcrJobStatusResponse(
        job_id="job-b", notice_id=2, status=NoticeOcrJobStatus.RUNNING
    )

    response = await get_notice_ocr_batch_status(job_ids=["job-a", "job-b"])

    assert [item.job_id for item in response.items] == ["job-a", "job-b"]
    assert response.items[0].status == NoticeOcrJobStatus.COMPLETED
    assert response.items[1].status == NoticeOcrJobStatus.RUNNING


async def test_get_notice_ocr_batch_status_dedupes_duplicate_job_ids():
    """배치 트리거(start_notice_ocr_batch)가 notice_id 중복을 순서 유지하며
    제거하는 것과 똑같이, 같은 job_id를 여러 번 넣어도 응답에 중복으로
    나가면 안 된다."""
    _JOBS["job-a"] = NoticeOcrJobStatusResponse(
        job_id="job-a", notice_id=1, status=NoticeOcrJobStatus.COMPLETED
    )

    response = await get_notice_ocr_batch_status(job_ids=["job-a", "job-a"])

    assert [item.job_id for item in response.items] == ["job-a"]


async def test_get_notice_ocr_batch_status_silently_skips_unknown_job_ids():
    """단건 조회(get_notice_ocr_status)는 모르는 job_id면 404를 내지만,
    배치 조회는 그중 일부가 잘못돼도 나머지 조회 자체가 실패하면 안 되므로
    조용히 결과에서 뺀다."""
    _JOBS["job-a"] = NoticeOcrJobStatusResponse(
        job_id="job-a", notice_id=1, status=NoticeOcrJobStatus.COMPLETED
    )

    response = await get_notice_ocr_batch_status(job_ids=["job-a", "존재하지-않는-job"])

    assert [item.job_id for item in response.items] == ["job-a"]


async def test_get_notice_ocr_batch_status_returns_empty_items_for_empty_input():
    response = await get_notice_ocr_batch_status(job_ids=[])

    assert response.items == []


def test_get_notice_ocr_batch_status_returns_200_when_job_ids_omitted_over_http():
    """함수를 직접 부르면 job_ids=[]가 그냥 파이썬 기본 인자라 늘 통과하지만,
    실제 HTTP에서는 Query(...)(필수)였다면 job_ids를 아예 안 보낼 때 422가
    난다 — FastAPI 계층까지 거쳐야 드러나는 문제라 TestClient로 확인한다."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.get("/api/internal/notices/ocr/batch/status")

    assert response.status_code == 200
    assert response.json() == {"items": []}

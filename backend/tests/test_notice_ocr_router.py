"""
tests/test_notice_ocr_router.py

api/notice_ocr.py의 순수 로직(_pick_ocr_target/_file_type_from_name)과
동시 트리거 가드(_has_active_job_for_notice)를 검증한다. 실제 다운로드/OCR
호출은 외부 네트워크가 필요해 여기서 다루지 않는다.
"""

import pytest

from app.api.notice_ocr import (
    _JOBS,
    _file_type_from_name,
    _has_active_job_for_notice,
    _pick_ocr_target,
)
from app.models.notice import NoticeAttachment
from app.schemas.notice_ocr import NoticeOcrJobStatus, NoticeOcrJobStatusResponse


@pytest.fixture(autouse=True)
def clear_jobs():
    _JOBS.clear()
    yield
    _JOBS.clear()


def _attachment(**overrides) -> NoticeAttachment:
    defaults = dict(id=1, notice_id=1, file_name="a.pdf", file_type="PDF", parsed_text=None)
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

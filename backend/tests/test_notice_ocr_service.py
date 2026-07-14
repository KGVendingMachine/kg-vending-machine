"""
tests/test_notice_ocr_service.py

ensure_notice_attachment_ocr — 1차 필터링 통과 후보에 한해 첨부파일을
온디맨드로 OCR하는 로직(2026-07-14 추가, docs/matching-pipeline.md 4단계
원래 설계를 따름)을 검증한다. DB/외부 크롤러/다운로더는 전부 monkeypatch로
대체한다.
"""

from unittest.mock import AsyncMock

import pytest

from app.models.notice import Notice, NoticeAttachment
from app.services import notice_ocr_service
from app.services.notice_ocr_service import ensure_notice_attachment_ocr

pytestmark = pytest.mark.anyio

_BIZINFO_SOURCE = "기업마당"


def _attachment(
    attachment_id: int, *, file_name: str, file_type: str, parsed_text: str | None
) -> NoticeAttachment:
    return NoticeAttachment(
        id=attachment_id,
        notice_id=1,
        file_name=file_name,
        file_url=f"https://example.com/{file_name}",
        file_type=file_type,
        parsed_text=parsed_text,
    )


async def test_returns_none_when_notice_not_found(monkeypatch):
    monkeypatch.setattr(
        notice_ocr_service, "get_notice_detail", AsyncMock(return_value=None)
    )

    result = await ensure_notice_attachment_ocr(session=None, notice_id=999)

    assert result is None


async def test_reuses_already_parsed_attachment_without_downloading(monkeypatch):
    notice = Notice(id=1, source_id=1, title="공고", external_id="1")
    monkeypatch.setattr(
        notice_ocr_service,
        "get_notice_detail",
        AsyncMock(return_value=(notice, _BIZINFO_SOURCE, None)),
    )
    already_parsed = _attachment(
        1, file_name="공고문.pdf", file_type="PDF", parsed_text="이미 뽑은 원문"
    )
    monkeypatch.setattr(
        notice_ocr_service,
        "get_notice_attachments",
        AsyncMock(return_value=[already_parsed]),
    )
    download_mock = AsyncMock()
    monkeypatch.setattr(
        notice_ocr_service, "download_and_extract_attachment", download_mock
    )

    result = await ensure_notice_attachment_ocr(session=None, notice_id=1)

    assert result is already_parsed
    download_mock.assert_not_called()


async def test_downloads_and_persists_text_when_not_yet_ocred(monkeypatch):
    notice = Notice(id=1, source_id=1, title="공고", external_id="1")
    monkeypatch.setattr(
        notice_ocr_service,
        "get_notice_detail",
        AsyncMock(return_value=(notice, _BIZINFO_SOURCE, None)),
    )
    target = _attachment(1, file_name="공고문.pdf", file_type="PDF", parsed_text=None)
    monkeypatch.setattr(
        notice_ocr_service, "get_notice_attachments", AsyncMock(return_value=[target])
    )
    monkeypatch.setattr(
        notice_ocr_service,
        "download_and_extract_attachment",
        AsyncMock(return_value="새로 추출한 원문"),
    )
    set_parsed_text_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(
        notice_ocr_service, "set_attachment_parsed_text", set_parsed_text_mock
    )

    result = await ensure_notice_attachment_ocr(session=None, notice_id=1)

    assert result is target
    assert result.parsed_text == "새로 추출한 원문"
    set_parsed_text_mock.assert_awaited_once_with(None, target.id, "새로 추출한 원문")


async def test_returns_none_when_no_ocr_target_attachment(monkeypatch):
    notice = Notice(id=1, source_id=1, title="공고", external_id="1")
    monkeypatch.setattr(
        notice_ocr_service,
        "get_notice_detail",
        AsyncMock(return_value=(notice, _BIZINFO_SOURCE, None)),
    )
    unsupported = _attachment(
        1, file_name="붙임.zip", file_type="ZIP", parsed_text=None
    )
    monkeypatch.setattr(
        notice_ocr_service,
        "get_notice_attachments",
        AsyncMock(return_value=[unsupported]),
    )

    result = await ensure_notice_attachment_ocr(session=None, notice_id=1)

    assert result is None


async def test_crawls_kstartup_attachments_when_none_stored_yet(monkeypatch):
    notice = Notice(id=1, source_id=1, title="공고", external_id="12345")
    monkeypatch.setattr(
        notice_ocr_service,
        "get_notice_detail",
        AsyncMock(return_value=(notice, notice_ocr_service.KSTARTUP_SOURCE_NAME, None)),
    )
    crawled_attachment = _attachment(
        2, file_name="공고문.hwp", file_type="HWP", parsed_text=None
    )
    get_attachments_mock = AsyncMock(side_effect=[[], [crawled_attachment]])
    monkeypatch.setattr(
        notice_ocr_service, "get_notice_attachments", get_attachments_mock
    )
    fetch_mock = AsyncMock(return_value=[("공고문.hwp", "https://example.com/a.hwp")])
    monkeypatch.setattr(notice_ocr_service, "fetch_kstartup_attachments", fetch_mock)
    save_attachment_mock = AsyncMock()
    monkeypatch.setattr(notice_ocr_service, "save_attachment", save_attachment_mock)
    monkeypatch.setattr(
        notice_ocr_service,
        "download_and_extract_attachment",
        AsyncMock(return_value="크롤링 후 추출한 원문"),
    )
    monkeypatch.setattr(
        notice_ocr_service,
        "set_attachment_parsed_text",
        AsyncMock(return_value=True),
    )

    result = await ensure_notice_attachment_ocr(session=None, notice_id=1)

    fetch_mock.assert_awaited_once_with(12345)
    save_attachment_mock.assert_awaited_once()
    assert result is crawled_attachment
    assert result.parsed_text == "크롤링 후 추출한 원문"


async def test_returns_none_when_download_fails(monkeypatch):
    notice = Notice(id=1, source_id=1, title="공고", external_id="1")
    monkeypatch.setattr(
        notice_ocr_service,
        "get_notice_detail",
        AsyncMock(return_value=(notice, _BIZINFO_SOURCE, None)),
    )
    target = _attachment(1, file_name="공고문.pdf", file_type="PDF", parsed_text=None)
    monkeypatch.setattr(
        notice_ocr_service, "get_notice_attachments", AsyncMock(return_value=[target])
    )
    monkeypatch.setattr(
        notice_ocr_service,
        "download_and_extract_attachment",
        AsyncMock(side_effect=RuntimeError("다운로드 실패")),
    )

    result = await ensure_notice_attachment_ocr(session=None, notice_id=1)

    assert result is None

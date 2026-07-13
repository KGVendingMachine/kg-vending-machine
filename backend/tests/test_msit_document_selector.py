"""
tests/test_msit_document_selector.py

services/msit_document_selector.py 테스트. 실제 OpenAI API는 호출하지
않고 client.chat.completions.create를 가짜로 대체한다
(tests/test_ai_normalizer.py와 동일한 패턴).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.notice import NoticeAttachment
from app.services.msit_document_selector import (
    _select_via_llm,
    select_msit_announcement_attachment,
)

pytestmark = pytest.mark.anyio


def _attachment(file_name: str, file_type: str) -> NoticeAttachment:
    return NoticeAttachment(file_name=file_name, file_type=file_type, file_url="u")


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _fake_client(side_effect: list) -> SimpleNamespace:
    create = AsyncMock(side_effect=side_effect)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )


async def test_returns_none_when_no_target_format_candidates():
    attachments = [_attachment("a.odt", "ODT"), _attachment("b.zip", "ZIP")]

    result = await select_msit_announcement_attachment(attachments)

    assert result is None


async def test_returns_single_format_candidate_without_llm_call():
    attachments = [
        _attachment("공고문.hwpx", "HWPX"),
        _attachment("첨부.odt", "ODT"),
        _attachment("양식.zip", "ZIP"),
    ]

    result = await select_msit_announcement_attachment(attachments)

    assert result.file_name == "공고문.hwpx"


async def test_keyword_filter_excludes_supplementary_documents():
    """실제 응답 샘플(2026-07-13)에서 확인한 패턴 - 공고문 hwpx/hwp에
    신청서식/매뉴얼 zip이 같이 오지만 이건 HWP/HWPX 포맷이 아니라서
    이미 1단계에서 걸러진다. 여기서는 공고문과 안내서가 둘 다
    HWP/HWPX인 경우(실제로 있었던 패턴)를 검증한다."""
    attachments = [
        _attachment("2026년 OO사업 공고문.hwpx", "HWPX"),
        _attachment("2026년 OO사업 공모안내서.hwpx", "HWPX"),
    ]

    result = await select_msit_announcement_attachment(attachments)

    assert result.file_name == "2026년 OO사업 공고문.hwpx"


async def test_falls_back_to_unfiltered_when_all_match_supplementary_keywords():
    """과탐지로 후보가 전부 제외되면(안내서/양식 키워드가 실제로는 공고문
    제목에 들어간 경우 등) 필터 적용 전 후보로 되돌아가 최소 하나는
    남긴다."""
    attachments = [_attachment("2026년 사업 안내서.hwp", "HWP")]

    result = await select_msit_announcement_attachment(attachments)

    assert result.file_name == "2026년 사업 안내서.hwp"


async def test_select_via_llm_picks_index_from_response():
    attachments = [
        _attachment("공모안내서.hwp", "HWP"),
        _attachment("공고문.hwp", "HWP"),
    ]
    client = _fake_client([_fake_response('{"index": 1}')])

    result = await _select_via_llm(attachments, client=client)

    assert result.file_name == "공고문.hwp"


async def test_select_via_llm_falls_back_to_first_candidate_on_malformed_response():
    attachments = [
        _attachment("공고문.hwp", "HWP"),
        _attachment("확인서.hwp", "HWP"),
    ]
    client = _fake_client([_fake_response("이건 JSON이 아님")])

    result = await _select_via_llm(attachments, client=client)

    assert result.file_name == "공고문.hwp"


async def test_select_via_llm_falls_back_when_index_out_of_range():
    attachments = [_attachment("공고문.hwp", "HWP")]
    client = _fake_client([_fake_response('{"index": 5}')])

    result = await _select_via_llm(attachments, client=client)

    assert result.file_name == "공고문.hwp"

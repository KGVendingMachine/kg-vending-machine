"""
tests/test_msit_client.py

crawler/msit_client.py의 순수 로직 테스트. 네트워크 호출은 하지 않는다.
"""

import pytest

from app.crawler.msit_client import _extract_items, _read_response_with_size_limit

pytestmark = pytest.mark.anyio


class _FakeStreamResponse:
    """httpx.Response의 aiter_bytes()만 흉내낸 가짜 — 실제 네트워크 없이
    _read_response_with_size_limit(순수 로직)만 검증하는 용도."""

    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


async def test_read_response_with_size_limit_returns_data_within_limit():
    response = _FakeStreamResponse([b"hello ", b"world"])

    result = await _read_response_with_size_limit(response, "test-source")

    assert result == b"hello world"


async def test_read_response_with_size_limit_rejects_oversized_response(monkeypatch):
    import app.crawler.msit_client as module

    monkeypatch.setattr(module, "_MAX_ATTACHMENT_SIZE_BYTES", 5)
    response = _FakeStreamResponse([b"way more than 5 bytes"])

    with pytest.raises(RuntimeError, match="허용 크기"):
        await _read_response_with_size_limit(response, "test-source")


def _sample_payload(items: list[dict]) -> dict:
    return {
        "response": [
            {"header": {"resultCode": "00", "resultMsg": "NORMAL_CODE"}},
            {"body": {"pageNo": "1", "totalCount": len(items), "items": items}},
        ]
    }


def test_extract_items_unwraps_item_and_file_wrappers():
    """실제 응답(2026-07-13 실측)은 item/file 각각을 {"item": {...}}/
    {"file": {...}}로 한 겹 더 감싼다 — 호출하는 쪽은 평탄한 dict를
    기대하므로(bizinfo_client.py/kstartup_client.py와 같은 계약) 풀어서
    반환해야 한다."""
    payload = _sample_payload(
        [
            {
                "item": {
                    "subject": "테스트 공고",
                    "pressDt": "2026-07-13",
                    "files": [
                        {"file": {"fileName": "a.pdf", "fileUrl": "https://x/a.pdf"}},
                        {"file": {"fileName": "b.hwp", "fileUrl": "https://x/b.hwp"}},
                    ],
                }
            }
        ]
    )

    items = _extract_items(payload)

    assert len(items) == 1
    assert items[0]["subject"] == "테스트 공고"
    assert items[0]["files"] == [
        {"fileName": "a.pdf", "fileUrl": "https://x/a.pdf"},
        {"fileName": "b.hwp", "fileUrl": "https://x/b.hwp"},
    ]


def test_extract_items_handles_item_without_files():
    payload = _sample_payload([{"item": {"subject": "첨부파일 없는 공고"}}])

    items = _extract_items(payload)

    assert items[0]["files"] == []


def test_extract_items_raises_when_result_code_not_normal():
    payload = {
        "response": [
            {"header": {"resultCode": "99", "resultMsg": "SERVICE ERROR"}},
            {"body": {"items": []}},
        ]
    }

    with pytest.raises(RuntimeError, match="오류를 반환"):
        _extract_items(payload)


def test_extract_items_raises_on_unexpected_structure():
    with pytest.raises(RuntimeError, match="예상과 다른 구조"):
        _extract_items({"unexpected": "shape"})

"""
tests/test_bizinfo_client.py

crawler/bizinfo_client.py의 순수 로직 테스트. 네트워크 호출은 하지 않는다.
"""

import pytest

from app.crawler.bizinfo_client import _read_response_with_size_limit

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
    """response.content로 그냥 받으면 크기 제한 없이 응답 전체를 메모리에
    올리는데, 배치 OCR로 여러 첨부파일을 동시에 다운로드할 때 서버 사이트가
    예상외로 큰 파일을 내려주면 서버 메모리를 위협할 수 있다(HWP/HWPX/PDF
    압축 해제 폭탄과 같은 종류의 문제). 실제로 몇백MB짜리 응답을 만들
    필요 없이 상한을 낮춰서 거부 로직만 검증한다."""
    import app.crawler.bizinfo_client as module

    monkeypatch.setattr(module, "_MAX_ATTACHMENT_SIZE_BYTES", 5)
    response = _FakeStreamResponse([b"way more than 5 bytes"])

    with pytest.raises(RuntimeError, match="허용 크기"):
        await _read_response_with_size_limit(response, "test-source")

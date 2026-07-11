"""
tests/test_extract.py

app/ocr/extract.py 테스트. HWP/HWPX 파싱, PDF 네이티브 텍스트/이미지
추출, 이미지 포맷 변환은 전부 동기(CPU 바운드) 함수라 asyncio.to_thread로
감싸져 있어야 한다 — 그렇지 않으면 FastAPI BackgroundTasks(요청과 같은
이벤트 루프)에서 실행될 때 그 시간만큼 서버 전체가 멈춘다(이슈 #61).

실제 HWP/PDF 샘플 파일 없이도 검증 가능하도록, 동기 로더를 "느린 동기
함수"로 monkeypatch해서 그동안 이벤트 루프가 계속 다른 코루틴을 처리할
수 있는지(heartbeat가 계속 틱하는지)를 직접 측정한다. asyncio.to_thread로
안 감싸져 있었다면 이 테스트는 실패한다(동기 sleep이 이벤트 루프
자체를 막아 heartbeat가 거의 못 틈).
"""

import asyncio
import time

import pytest

from app.ocr import extract as extract_module
from app.ocr.extract import extract_text

pytestmark = pytest.mark.anyio

_BLOCKING_DURATION_SECONDS = 0.3
_HEARTBEAT_INTERVAL_SECONDS = 0.02


async def _run_with_heartbeat(coro):
    """coro를 실행하는 동안 heartbeat 코루틴이 몇 번이나 틱했는지 같이 잰다."""
    tick_count = 0

    async def heartbeat():
        nonlocal tick_count
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
            tick_count += 1

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        result = await coro
    finally:
        heartbeat_task.cancel()
    return result, tick_count


async def test_hwp_extraction_does_not_block_event_loop(monkeypatch, tmp_path):
    file_path = tmp_path / "sample.hwp"
    file_path.write_bytes(b"dummy")

    def fake_load_hwp_text(path: str) -> str:
        time.sleep(_BLOCKING_DURATION_SECONDS)  # 동기 블로킹 흉내
        return "HWP 본문"

    monkeypatch.setattr(extract_module, "_load_hwp_text", fake_load_hwp_text)
    monkeypatch.setattr(extract_module, "_extract_images_safely", lambda *a, **k: [])

    (text, file_type), tick_count = await _run_with_heartbeat(
        extract_text(str(file_path))
    )

    assert (text, file_type) == ("HWP 본문", "HWP")
    # asyncio.to_thread로 감싸져 있지 않았다면 동기 sleep이 이벤트 루프
    # 자체를 막아 heartbeat가 거의 못 틈(0~1회). 감싸져 있으면 0.3초 동안
    # 0.02초 간격으로 대부분 틱해야 한다.
    assert tick_count >= 5


async def test_hwpx_extraction_does_not_block_event_loop(monkeypatch, tmp_path):
    file_path = tmp_path / "sample.hwpx"
    file_path.write_bytes(b"dummy")

    def fake_load_hwpx_text(path: str) -> str:
        time.sleep(_BLOCKING_DURATION_SECONDS)
        return "HWPX 본문"

    monkeypatch.setattr(extract_module, "_load_hwpx_text", fake_load_hwpx_text)
    monkeypatch.setattr(extract_module, "_extract_images_safely", lambda *a, **k: [])

    (text, file_type), tick_count = await _run_with_heartbeat(
        extract_text(str(file_path))
    )

    assert (text, file_type) == ("HWPX 본문", "HWPX")
    assert tick_count >= 5


async def test_pdf_native_text_extraction_does_not_block_event_loop(
    monkeypatch, tmp_path
):
    file_path = tmp_path / "sample.pdf"
    file_path.write_bytes(b"dummy")

    def fake_extract_native_pdf_text(path: str) -> str:
        time.sleep(_BLOCKING_DURATION_SECONDS)
        return "네이티브 텍스트가 충분히 길어서 CLOVA로 안 넘어가야 함" * 5

    monkeypatch.setattr(
        extract_module, "_extract_native_pdf_text", fake_extract_native_pdf_text
    )
    monkeypatch.setattr(extract_module, "_extract_images_safely", lambda *a, **k: [])

    (text, file_type), tick_count = await _run_with_heartbeat(
        extract_text(str(file_path))
    )

    assert file_type == "PDF"
    assert "네이티브 텍스트" in text
    assert tick_count >= 5


async def test_image_conversion_does_not_block_event_loop(monkeypatch):
    """CLOVA 미지원 포맷(bmp 등)을 png로 변환하는 동기 PIL 호출도
    asyncio.to_thread로 감싸져 있어야 한다."""

    def fake_convert_to_png(data: bytes) -> bytes:
        time.sleep(_BLOCKING_DURATION_SECONDS)
        return b"converted-png-bytes"

    async def fake_call_clova_ocr_bytes(
        data: bytes, image_format: str, name: str
    ) -> str:
        assert data == b"converted-png-bytes"
        assert image_format == "png"
        return "인식된 텍스트"

    monkeypatch.setattr(extract_module, "_convert_to_png", fake_convert_to_png)
    monkeypatch.setattr(
        extract_module, "call_clova_ocr_bytes", fake_call_clova_ocr_bytes
    )

    result, tick_count = await _run_with_heartbeat(
        extract_module._ocr_image_bytes(b"raw-bmp-bytes", ".bmp")
    )

    assert result == "인식된 텍스트"
    assert tick_count >= 5

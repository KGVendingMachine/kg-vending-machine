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


async def test_pdf_native_extraction_times_out_instead_of_hanging_forever(
    monkeypatch, tmp_path
):
    """실제로 재현함(2026-07-12): 100KB짜리 FlateDecode 압축 스트림을 극단적으로
    압축해 넣은 PDF를 pdfplumber.extract_text()에 넘기면 30초+ 동안 CPU를
    점유한 채 끝나지 않았다(압축 해제 폭탄, hwp/hwpx의 zlib/zip bomb와 같은
    문제지만 pdfplumber/pypdf 내부라 우리가 직접 크기 제한을 걸 수 없다).
    사업계획서 업로드로 로그인한 일반 사용자가 도달 가능한 DoS 벡터라
    처리 시간 자체에 상한(asyncio.wait_for)을 걸어, 시간 초과 시 CLOVA
    OCR 폴백으로 넘어가고(빈 문자열 취급) 요청 자체가 무한정 멈추지
    않게 해야 한다."""
    file_path = tmp_path / "sample.pdf"
    file_path.write_bytes(b"dummy")

    monkeypatch.setattr(extract_module, "_PDF_EXTRACTION_TIMEOUT_SECONDS", 0.05)

    def hanging_extract_native_pdf_text(path: str) -> str:
        time.sleep(_BLOCKING_DURATION_SECONDS)  # 상한(0.05초)보다 훨씬 긺
        return "이 값은 절대 안 쓰여야 한다"

    async def fake_fetch_clova_ocr_text(path: str) -> str:
        return "CLOVA 폴백 텍스트"

    monkeypatch.setattr(
        extract_module, "_extract_native_pdf_text", hanging_extract_native_pdf_text
    )
    monkeypatch.setattr(
        extract_module, "fetch_clova_ocr_text", fake_fetch_clova_ocr_text
    )

    t0 = time.monotonic()
    text, file_type = await extract_text(str(file_path))
    elapsed = time.monotonic() - t0

    assert text == "CLOVA 폴백 텍스트"
    # 상한(0.05초) 근처에서 끝나야 한다 — 실제 블로킹 시간(0.3초)까지
    # 기다렸다면 시간 초과가 작동하지 않은 것.
    assert elapsed < _BLOCKING_DURATION_SECONDS


async def test_extract_text_strips_nul_bytes(monkeypatch, tmp_path):
    """PostgreSQL은 인코딩과 무관하게 text/varchar 컬럼에 NUL(0x00) 바이트를
    저장하지 못한다(CharacterNotInRepertoireError). 실제 공고 PDF 샘플에서
    pdfplumber가 이 바이트를 뽑아내는 걸 확인했다(2026-07-11) — 이 함수
    결과를 그대로 DB에 저장하는 모든 호출자(공고 OCR, 사업계획서 분석)가
    영향받으므로 반환 전에 제거해야 한다."""
    file_path = tmp_path / "sample.pdf"
    file_path.write_bytes(b"dummy")

    def fake_extract_native_pdf_text(path: str) -> str:
        return "본문에 NUL\x00바이트가 섞여있음" * 5

    monkeypatch.setattr(
        extract_module, "_extract_native_pdf_text", fake_extract_native_pdf_text
    )
    monkeypatch.setattr(extract_module, "_extract_images_safely", lambda *a, **k: [])

    text, file_type = await extract_text(str(file_path))

    assert "\x00" not in text

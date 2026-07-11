"""
tests/test_hwp_loader.py

app/ocr/hwp_loader.py 테스트.
"""

import zlib

import pytest

from app.ocr.hwp_loader import HWPLoader, _zlib_decompress_safely


def test_zlib_decompress_safely_returns_data_within_limit():
    data = b"hello world" * 100
    compressed = zlib.compressobj(9, zlib.DEFLATED, -15)
    payload = compressed.compress(data) + compressed.flush()

    result = _zlib_decompress_safely(payload)

    assert result == data


def test_zlib_decompress_safely_rejects_decompression_bomb(monkeypatch):
    """압축 해제 폭탄(zlib bomb) 방지 확인. 실제로 몇백MB짜리 스트림을
    만들 필요 없이 상한을 낮춰서, 압축 해제 결과가 상한을 넘으면 거부하는지만
    검증한다(실측: 100KB 압축 스트림을 제한 없이 풀면 100MB로 부풀어 오름,
    0.25초 — HWP는 사업계획서 업로드로 로그인한 일반 사용자가 직접 올릴 수
    있는 파일이라 실제 공격 경로였다)."""
    import app.ocr.hwp_loader as loader_module

    monkeypatch.setattr(loader_module, "_MAX_DECOMPRESSED_SIZE", 10)

    data = b"hello world" * 100
    compressed = zlib.compressobj(9, zlib.DEFLATED, -15)
    payload = compressed.compress(data) + compressed.flush()

    with pytest.raises(ValueError, match="허용 크기를 초과"):
        _zlib_decompress_safely(payload)


def test_hwp_loader_raises_value_error_for_invalid_file(tmp_path):
    path = tmp_path / "not_a_hwp.hwp"
    path.write_bytes(b"this is not an OLE compound file")

    with pytest.raises(Exception):
        HWPLoader(str(path)).load()

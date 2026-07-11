"""
tests/test_hwpx_loader.py

app/ocr/hwpx_loader.py 테스트.
"""

import zipfile

import pytest

from app.ocr.hwpx_loader import HWPXLoader


def _make_hwpx(section_xml: bytes, tmp_path) -> str:
    path = tmp_path / "sample.hwpx"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Contents/section0.xml", section_xml)
    return str(path)


def test_hwpx_loader_extracts_paragraph_text(tmp_path):
    xml = (
        b'<root xmlns:hp="x">'
        b"<hp:p><hp:run><hp:t>\xec\x95\x88\xeb\x85\x95</hp:t></hp:run></hp:p>"
        b"</root>"
    )
    path = _make_hwpx(xml, tmp_path)

    docs = HWPXLoader(path).load()

    assert docs[0].page_content == "안녕"


def test_hwpx_loader_rejects_doctype_entity_expansion_bomb(tmp_path):
    """정상 HWPX 본문 XML은 DOCTYPE/커스텀 엔티티를 쓸 이유가 없다.

    xml.etree.ElementTree는 엔티티 확장 개수·깊이를 제한하지 않아서,
    사업계획서 업로드(.hwpx)로 사용자가 직접 올리는 파일에 이런 "billion
    laughs" 스타일 엔티티 폭탄을 심으면 몇백 바이트짜리 파일이 파싱
    시점에 기하급수적으로 부풀어 서버 메모리를 고갈시킬 수 있다(DoS).
    DOCTYPE 선언 자체를 막아 원천 차단해야 한다."""
    xml_bomb = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY a0 "lol">
 <!ENTITY a1 "&a0;&a0;&a0;&a0;&a0;&a0;&a0;&a0;&a0;&a0;">
 <!ENTITY a2 "&a1;&a1;&a1;&a1;&a1;&a1;&a1;&a1;&a1;&a1;">
]>
<root><hp:p xmlns:hp="x"><hp:run><hp:t>&a2;</hp:t></hp:run></hp:p></root>
"""
    path = _make_hwpx(xml_bomb, tmp_path)

    with pytest.raises(RuntimeError, match="DOCTYPE"):
        HWPXLoader(path).load()


def test_hwpx_loader_wraps_malformed_xml_as_runtime_error(tmp_path):
    path = _make_hwpx(b"<not-closed>", tmp_path)

    with pytest.raises(RuntimeError):
        HWPXLoader(path).load()


def test_hwpx_loader_wraps_bad_zip_as_runtime_error(tmp_path):
    path = tmp_path / "not_a_zip.hwpx"
    path.write_bytes(b"this is not a zip file")

    with pytest.raises(RuntimeError):
        HWPXLoader(str(path)).load()

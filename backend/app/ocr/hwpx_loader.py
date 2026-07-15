import re
import zipfile
import xml.etree.ElementTree as ET
from collections.abc import Iterator

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document

_SECTION_NUMBER_RE = re.compile(r"section(\d+)\.xml$")


def _section_number(name: str) -> int:
    """section{n}.xml 파일명에서 숫자만 뽑는다 (없으면 0)."""
    match = _SECTION_NUMBER_RE.search(name)
    return int(match.group(1)) if match else 0


_IMAGE_EXTENSIONS = (".bmp", ".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff")


def _reject_unsafe_xml(xml_data: bytes) -> None:
    """XML 엔티티 확장 공격("billion laughs") 방지.

    ElementTree는 엔티티 확장에 제한이 없어(실측: 365바이트 → 30만자) DoS가
    가능하므로, 정상 HWPX엔 없는 DOCTYPE 선언 자체를 막아 원천 차단한다.
    """
    if b"<!DOCTYPE" in xml_data:
        raise RuntimeError(
            "HWPX 문서에서 허용되지 않는 XML 선언(DOCTYPE)이 발견됐습니다."
        )


# 압축 해제 폭탄(zip bomb) 방지용 상한. 실측: 100KB 압축 항목이 제한 없이
# 풀면 100MB로 부풀어 오름(0.3초) — 사용자가 직접 올리는 HWPX라 악용 가능.
_MAX_UNCOMPRESSED_ENTRY_SIZE = 100 * 1024 * 1024


def _read_zip_entry_safely(zf: zipfile.ZipFile, name: str) -> bytes:
    """압축 해제 전 선언된 크기(ZipInfo.file_size)를 먼저 확인해 과도한 항목을 거부한다.

    실제로 풀어보기 전에 거부하므로 압축 해제 자체가 일어나지 않는다.
    """
    info = zf.getinfo(name)
    if info.file_size > _MAX_UNCOMPRESSED_ENTRY_SIZE:
        raise RuntimeError(
            f"HWPX 내부 파일이 너무 큽니다: {name} ({info.file_size} bytes)"
        )
    return zf.read(name)


def extract_embedded_images(file_path: str) -> list[tuple[bytes, str]]:
    """HWPX 안에 그림으로 삽입된 표/차트 등의 원본 이미지를 꺼낸다.

    통째로 그림으로 붙여넣은 슬라이드(SWOT/PEST 등)를 OCR에 넘기기 위해 추출한다.
    """
    images = []
    with zipfile.ZipFile(file_path, "r") as zf:
        for name in zf.namelist():
            if not name.startswith("BinData/"):
                continue
            ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in _IMAGE_EXTENSIONS:
                images.append((_read_zip_entry_safely(zf, name), ext))
    return images


class HWPXLoader(BaseLoader):
    """HWPX(OWPML) 파일에서 본문 텍스트를 추출하는 로더.

    HWPX는 zip 컨테이너 안에 XML로 본문을 담고 있어, HWP와 달리 OLE/압축
    해제 없이 zipfile + XML 파싱만으로 텍스트를 뽑을 수 있다.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path

    def lazy_load(self) -> Iterator[Document]:
        """HWPX 본문 section*.xml을 순서대로 파싱해 문단 텍스트로 합친다."""
        text_content = []

        try:
            with zipfile.ZipFile(self.file_path, "r") as zf:
                # 문자열 정렬은 section10.xml이 section2.xml보다 앞에 와서
                # 섹션 10개 넘는 문서의 순서가 뒤섞이므로, 숫자로 정렬한다.
                section_files = sorted(
                    (
                        name
                        for name in zf.namelist()
                        if name.startswith("Contents/section") and name.endswith(".xml")
                    ),
                    key=_section_number,
                )

                for section_file in section_files:
                    xml_data = _read_zip_entry_safely(zf, section_file)
                    _reject_unsafe_xml(xml_data)
                    root = ET.fromstring(xml_data)

                    # 한 문단 안에서도 서식이 바뀌는 지점마다 <hp:run>이 나뉘어
                    # <hp:t>가 여러 개 생기므로, 'p' 태그 단위로 run 텍스트를 모아 확정한다.
                    current_paragraph: list[str] = []
                    for node in root.iter():
                        if node.tag.endswith("}p") or node.tag == "p":
                            if current_paragraph:
                                text_content.append("".join(current_paragraph))
                                current_paragraph = []
                        elif (node.tag.endswith("}t") or node.tag == "t") and node.text:
                            current_paragraph.append(node.text)
                    if current_paragraph:
                        text_content.append("".join(current_paragraph))
        except (zipfile.BadZipFile, ET.ParseError) as exc:
            raise RuntimeError(
                f"HWPX 파일을 파싱하는 중 오류가 발생했습니다: {exc}"
            ) from exc

        full_text = "\n".join(text_content)
        yield Document(page_content=full_text, metadata={"source": self.file_path})

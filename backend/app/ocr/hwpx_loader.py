import re
import zipfile
import xml.etree.ElementTree as ET
from collections.abc import Iterator

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document

_SECTION_NUMBER_RE = re.compile(r"section(\d+)\.xml$")


def _section_number(name: str) -> int:
    match = _SECTION_NUMBER_RE.search(name)
    return int(match.group(1)) if match else 0


_IMAGE_EXTENSIONS = (".bmp", ".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff")


def extract_embedded_images(file_path: str) -> list[tuple[bytes, str]]:
    """HWPX 안에 그림으로 삽입된 표/차트 등의 원본 이미지를 꺼낸다.

    본문(Contents/section*.xml)의 t 태그에는 텍스트로 안 남고 통째로
    그림으로 붙여넣은 슬라이드(예: SWOT/PEST 분석)가 실제 샘플에서
    발견되어, 이 이미지들을 따로 OCR에 넘기기 위해 추출한다.
    Preview/PrvImage.png는 문서 전체 축소 미리보기라 내용이 아니므로 뺀다.
    """
    images = []
    with zipfile.ZipFile(file_path, "r") as zf:
        for name in zf.namelist():
            if not name.startswith("BinData/"):
                continue
            ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in _IMAGE_EXTENSIONS:
                images.append((zf.read(name), ext))
    return images


class HWPXLoader(BaseLoader):
    """HWPX(OWPML) 파일에서 본문 텍스트를 추출하는 로더.

    HWPX는 zip 컨테이너 안에 XML로 본문을 담고 있어, HWP와 달리 OLE/압축
    해제 없이 zipfile + XML 파싱만으로 텍스트를 뽑을 수 있다.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path

    def lazy_load(self) -> Iterator[Document]:
        text_content = []

        try:
            with zipfile.ZipFile(self.file_path, "r") as zf:
                # HWPX 내부 본문 XML 파일 목록 (Contents/section0.xml, section1.xml ...)
                # 문자열로 그냥 정렬하면 section10.xml이 section2.xml보다
                # 앞에 와서 섹션이 10개 넘는 문서는 본문 순서가 뒤섞인다
                # (실제로 재현해서 확인함) — 번호를 뽑아 숫자로 정렬한다.
                section_files = sorted(
                    (
                        name
                        for name in zf.namelist()
                        if name.startswith("Contents/section") and name.endswith(".xml")
                    ),
                    key=_section_number,
                )

                for section_file in section_files:
                    xml_data = zf.read(section_file)
                    root = ET.fromstring(xml_data)

                    # HWPX(OWPML) 표준의 텍스트 태그는 보통 't' 또는 네임스페이스를
                    # 포함한 '{...}t' 형태이고, 문단 태그는 'p'/'{...}p' 형태다.
                    # 한 문단(<hp:p>) 안에서도 글자 서식(굵게/색 등)이 바뀌는
                    # 지점마다 <hp:run>이 나뉘어 <hp:t>가 여러 개 생긴다 — 이걸
                    # 문단 구분 없이 전부 개별 줄로 이어붙이면 한 문장이 서식
                    # 경계에서 줄바꿈으로 잘린다(실제 샘플에서 "어르신들의 건강
                    # 상태에 대한"과 "주관적 판단으로 대처 오류 발생"이 한
                    # 문장인데 두 줄로 쪼개지는 것을 확인함). 'p' 태그를 만날
                    # 때마다 지금까지 모은 run 텍스트를 한 문단으로 확정하고,
                    # 그 사이에 나온 't' 텍스트는 구분자 없이 이어붙인다 — 표
                    # 셀 안에 중첩된 문단도 자기 차례에 똑같이 처리되므로 표
                    # 안팎을 구분해서 따로 다룰 필요가 없다.
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

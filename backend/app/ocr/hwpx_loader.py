import zipfile
import xml.etree.ElementTree as ET
from collections.abc import Iterator

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document


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
                section_files = sorted(
                    name
                    for name in zf.namelist()
                    if name.startswith("Contents/section") and name.endswith(".xml")
                )

                for section_file in section_files:
                    xml_data = zf.read(section_file)
                    root = ET.fromstring(xml_data)

                    # HWPX(OWPML) 표준의 텍스트 태그는 보통 't' 또는 네임스페이스를
                    # 포함한 '{...}t' 형태라, 태그 이름이 't'로 끝나는 요소를 순회한다.
                    for node in root.iter():
                        if node.tag.endswith("}t") or node.tag == "t":
                            if node.text:
                                text_content.append(node.text)
        except (zipfile.BadZipFile, ET.ParseError) as exc:
            raise RuntimeError(
                f"HWPX 파일을 파싱하는 중 오류가 발생했습니다: {exc}"
            ) from exc

        full_text = "\n".join(text_content)
        yield Document(page_content=full_text, metadata={"source": self.file_path})

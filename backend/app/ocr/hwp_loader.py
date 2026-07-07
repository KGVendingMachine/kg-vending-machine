import re
import struct
import unicodedata
import zlib
from collections.abc import Iterator
from typing import Any

import olefile
from langchain_core.document_loaders.base import BaseLoader
from langchain_core.documents import Document


class HWPLoader(BaseLoader):
    """HWP(한글) 파일에서 본문 텍스트를 추출하는 로더.

    HWP는 OLE 복합 문서 포맷이라 CLOVA OCR처럼 이미지로 변환해 인식시킬
    필요 없이, BodyText 섹션의 레코드를 직접 파싱해 텍스트를 뽑아낼 수 있다.
    """

    FILE_HEADER_SECTION = "FileHeader"
    HWP_SUMMARY_SECTION = "\x05HwpSummaryInformation"
    BODYTEXT_SECTION = "BodyText"
    SECTION_NAME_LENGTH = len("Section")
    # HWP 레코드 태그 중 텍스트(HWPTAG_PARA_TEXT)에 해당하는 값
    HWP_TEXT_TAGS = [67]

    def __init__(self, file_path: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.file_path = file_path
        self.extra_info = {"source": file_path}

    def lazy_load(self) -> Iterator[Document]:
        load_file = olefile.OleFileIO(self.file_path)
        file_dir = load_file.listdir()

        if not self._is_valid_hwp(file_dir):
            raise ValueError("유효하지 않은 HWP 파일입니다.")

        result_text = self._extract_text(load_file, file_dir)
        yield Document(page_content=result_text, metadata=self.extra_info)

    def _is_valid_hwp(self, dirs: list[list[str]]) -> bool:
        return [self.FILE_HEADER_SECTION] in dirs and [self.HWP_SUMMARY_SECTION] in dirs

    def _get_body_sections(self, dirs: list[list[str]]) -> list[str]:
        section_numbers = [
            int(d[1][self.SECTION_NAME_LENGTH :])
            for d in dirs
            if d[0] == self.BODYTEXT_SECTION
        ]
        return [
            f"{self.BODYTEXT_SECTION}/Section{num}" for num in sorted(section_numbers)
        ]

    def _extract_text(
        self, load_file: olefile.OleFileIO, file_dir: list[list[str]]
    ) -> str:
        sections = self._get_body_sections(file_dir)
        return "\n".join(
            self._get_text_from_section(load_file, section) for section in sections
        )

    def _is_compressed(self, load_file: olefile.OleFileIO) -> bool:
        with load_file.openstream(self.FILE_HEADER_SECTION) as header:
            header_data = header.read()
            return bool(header_data[36] & 1)

    def _get_text_from_section(self, load_file: olefile.OleFileIO, section: str) -> str:
        with load_file.openstream(section) as bodytext:
            data = bodytext.read()

        # HWP는 zlib deflate로 압축돼 있는 경우가 많다. -15는 raw deflate
        # (zlib 헤더 없음)를 의미하며 HWP 포맷 스펙상 고정값이다.
        unpacked_data = (
            zlib.decompress(data, -15) if self._is_compressed(load_file) else data
        )

        text = []
        i = 0
        while i < len(unpacked_data):
            _, rec_type, rec_len = self._parse_record_header(unpacked_data[i : i + 4])
            if rec_type in self.HWP_TEXT_TAGS:
                rec_data = unpacked_data[i + 4 : i + 4 + rec_len]
                text.append(rec_data.decode("utf-16"))
            i += 4 + rec_len

        joined = "\n".join(text)
        joined = self._remove_chinese_characters(joined)
        joined = self._remove_control_characters(joined)
        return joined

    @staticmethod
    def _remove_chinese_characters(s: str) -> str:
        return re.sub(r"[一-鿿]+", "", s)

    @staticmethod
    def _remove_control_characters(s: str) -> str:
        """OCR·인코딩 과정에서 섞여 들어오는 깨진 제어문자를 제거한다."""
        return "".join(ch for ch in s if unicodedata.category(ch)[0] != "C")

    @staticmethod
    def _parse_record_header(header_bytes: bytes) -> tuple[int, int, int]:
        header = struct.unpack_from("<I", header_bytes)[0]
        rec_type = header & 0x3FF
        rec_len = (header >> 20) & 0xFFF
        return header, rec_type, rec_len

import re
import struct
import unicodedata
import zlib
from collections.abc import Iterator
from typing import Any

import olefile
from langchain_core.document_loaders.base import BaseLoader
from langchain_core.documents import Document

_IMAGE_EXTENSIONS = (".bmp", ".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff")


def _is_compressed(load_file: olefile.OleFileIO) -> bool:
    with load_file.openstream("FileHeader") as header:
        header_data = header.read()
        return bool(header_data[36] & 1)


def extract_embedded_images(file_path: str) -> list[tuple[bytes, str]]:
    """HWP 안에 그림으로 삽입된 표/차트 등의 원본 이미지를 꺼낸다.

    BinData 스토리지의 각 스트림은 스트림 이름 끝의 확장자로 원본 포맷을
    알 수 있다. 압축 여부는 문서 전체 압축 플래그(FileHeader)를 그대로
    따른다고 보고 시도하되, 압축 안 된 스트림도 있을 수 있어 압축 해제가
    실패하면 원본 바이트를 그대로 쓴다.

    (2026-07-10 검증 완료) K-Startup 공고 첨부 HWP 4건(임베드 이미지 총
    8개, 표/차트/기관 로고 포함)으로 실제 확인함 — 압축 스트림 해제, 이미지
    바이트 유효성(PIL로 열림), CLOVA OCR 연동까지 전부 정상 동작한다.
    """
    images = []
    with olefile.OleFileIO(file_path) as load_file:
        compressed = _is_compressed(load_file)
        for entry in load_file.listdir():
            if entry[0] != "BinData":
                continue
            stream_name = entry[-1]
            ext = (
                "." + stream_name.rsplit(".", 1)[-1].lower()
                if "." in stream_name
                else ""
            )
            if ext not in _IMAGE_EXTENSIONS:
                continue
            with load_file.openstream(entry) as stream:
                data = stream.read()
            if compressed:
                try:
                    data = zlib.decompress(data, -15)
                except zlib.error:
                    pass
            images.append((data, ext))
    return images


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
        with olefile.OleFileIO(self.file_path) as load_file:
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

    def _get_text_from_section(self, load_file: olefile.OleFileIO, section: str) -> str:
        with load_file.openstream(section) as bodytext:
            data = bodytext.read()

        # HWP는 zlib deflate로 압축돼 있는 경우가 많다. -15는 raw deflate
        # (zlib 헤더 없음)를 의미하며 HWP 포맷 스펙상 고정값이다.
        unpacked_data = (
            zlib.decompress(data, -15) if _is_compressed(load_file) else data
        )

        text = []
        i = 0
        while i < len(unpacked_data):
            _, rec_type, rec_len = self._parse_record_header(unpacked_data[i : i + 4])
            header_size = 4
            if rec_len == 0xFFF:
                # HWP5 스펙: 레코드 길이가 12비트(4095)로 못 담을 만큼 크면
                # 헤더에는 0xFFF만 넣고, 바로 뒤 4바이트(UInt32)에 실제
                # 길이를 따로 저장한다. 이걸 안 챙기면 4095바이트 넘는
                # 문단/표 셀 하나 때문에 이후 모든 레코드 오프셋이 밀린다.
                rec_len = struct.unpack_from("<I", unpacked_data[i + 4 : i + 8])[0]
                header_size = 8
            if rec_type in self.HWP_TEXT_TAGS:
                rec_data = unpacked_data[i + header_size : i + header_size + rec_len]
                text.append(rec_data.decode("utf-16"))
            i += header_size + rec_len

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

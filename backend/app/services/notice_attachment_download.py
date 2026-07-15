"""공고 첨부파일 하나를 다운로드해 텍스트를 추출하는 로직.

notice_ocr.py(단건 OCR)와 notice_normalization_service.py(정규화) 양쪽이 공유해서 쓴다.
"""

import tempfile
from pathlib import Path

from app.crawler.bizinfo_client import download_bizinfo_attachment
from app.crawler.kstartup_attachment_client import download_kstartup_attachment
from app.crawler.msit_client import download_msit_attachment
from app.models.notice import NoticeAttachment
from app.ocr.extract import extract_text
from app.services.notice_collection_service import (
    KSTARTUP_SOURCE_NAME,
    MSIT_SOURCE_NAME,
)

_SUFFIX_BY_FILE_TYPE = {"PDF": ".pdf", "HWP": ".hwp", "HWPX": ".hwpx"}


async def download_and_extract_attachment(
    source_name: str, attachment: NoticeAttachment
) -> str:
    """첨부파일을 다운로드해 텍스트를 추출한다.

    다운로드/추출 실패는 예외로 그대로 전파해 호출하는 쪽이 처리를 결정하게 한다.
    """
    if source_name == KSTARTUP_SOURCE_NAME:
        data = await download_kstartup_attachment(attachment.file_url)
    elif source_name == MSIT_SOURCE_NAME:
        data = await download_msit_attachment(attachment.file_url)
    else:
        data = await download_bizinfo_attachment(attachment.file_url)

    suffix = _SUFFIX_BY_FILE_TYPE.get(attachment.file_type or "", ".pdf")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name
    try:
        Path(tmp_path).write_bytes(data)
        text, _ = await extract_text(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return text

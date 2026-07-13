"""
services/notice_attachment_download.py

공고 첨부파일 하나를 다운로드해 텍스트를 추출하는 로직. app/api/notice_ocr.py(단건 OCR
트리거)와 app/services/notice_normalization_service.py(정규화, 후보 전부 OCR) 양쪽에서
같은 다운로드·추출 로직을 써야 해서 여기서 공유한다 — 원래 notice_ocr.py에만 있던
로직을 그대로 옮긴 것이라 동작 자체는 바뀌지 않았다.
"""

import tempfile
from pathlib import Path

from app.crawler.bizinfo_client import download_bizinfo_attachment
from app.crawler.kstartup_attachment_client import download_kstartup_attachment
from app.models.notice import NoticeAttachment
from app.ocr.extract import extract_text
from app.services.notice_collection_service import KSTARTUP_SOURCE_NAME

_SUFFIX_BY_FILE_TYPE = {"PDF": ".pdf", "HWP": ".hwp", "HWPX": ".hwpx"}


async def download_and_extract_attachment(
    source_name: str, attachment: NoticeAttachment
) -> str:
    """첨부파일을 다운로드해 텍스트를 추출한다.

    다운로드 실패, 텍스트 추출 실패 모두 예외를 그대로 전파한다 — 호출하는 쪽이
    "이 후보는 실패했다"로 처리할지, 유일한 후보라 그대로 에러로 전파할지 결정한다.
    """
    if source_name == KSTARTUP_SOURCE_NAME:
        data = await download_kstartup_attachment(attachment.file_url)
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

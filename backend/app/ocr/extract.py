from pathlib import Path

from app.ocr.clova_ocr_client import fetch_clova_ocr_text
from app.ocr.hwp_loader import HWPLoader
from app.ocr.hwpx_loader import HWPXLoader

# business_plan.file_type에 그대로 저장할 값
_FILE_TYPE_BY_SUFFIX = {
    ".hwp": "HWP",
    ".hwpx": "HWPX",
    ".pdf": "PDF",
    ".jpg": "IMAGE",
    ".jpeg": "IMAGE",
    ".png": "IMAGE",
    ".tiff": "IMAGE",
}


async def extract_text(file_path: str) -> tuple[str, str]:
    """파일 확장자에 맞는 로더로 본문 텍스트를 추출한다.

    HWP/HWPX는 문서 자체에 텍스트가 있어 로컬에서 바로 파싱하고,
    PDF/이미지는 텍스트 레이어가 없다고 보고 CLOVA OCR을 호출한다.

    Returns:
        (추출된 텍스트, business_plan.file_type에 저장할 파일 유형)
    """
    suffix = Path(file_path).suffix.lower()
    if suffix not in _FILE_TYPE_BY_SUFFIX:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {suffix}")

    file_type = _FILE_TYPE_BY_SUFFIX[suffix]

    if suffix == ".hwp":
        text = HWPLoader(file_path).load()[0].page_content
    elif suffix == ".hwpx":
        text = HWPXLoader(file_path).load()[0].page_content
    else:
        text = await fetch_clova_ocr_text(file_path)

    return text, file_type

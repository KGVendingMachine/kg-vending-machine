import io
from pathlib import Path

from PIL import Image

from app.ocr.clova_ocr_client import call_clova_ocr_bytes, fetch_clova_ocr_text
from app.ocr.hwp_loader import HWPLoader
from app.ocr.hwp_loader import extract_embedded_images as extract_hwp_images
from app.ocr.hwpx_loader import HWPXLoader
from app.ocr.hwpx_loader import extract_embedded_images as extract_hwpx_images

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
# CLOVA OCR이 그대로 받아주는 이미지 포맷 (bmp/gif 등은 여기 없으면 png로 변환)
_CLOVA_NATIVE_FORMATS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


async def extract_text(file_path: str) -> tuple[str, str]:
    """파일 확장자에 맞는 로더로 본문 텍스트를 추출한다.

    HWP/HWPX는 문서 자체에 있는 텍스트를 로컬에서 바로 파싱하고, 거기에
    더해 문서 안에 그림으로 삽입된 표/차트(본문 텍스트로는 안 잡히는
    내용, 실제 샘플에서 확인함)도 CLOVA OCR로 인식해 뒤에 이어붙인다.
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
        text = await _append_embedded_image_text(text, extract_hwp_images(file_path))
    elif suffix == ".hwpx":
        text = HWPXLoader(file_path).load()[0].page_content
        text = await _append_embedded_image_text(text, extract_hwpx_images(file_path))
    else:
        text = await fetch_clova_ocr_text(file_path)

    return text, file_type


async def _append_embedded_image_text(
    text: str, images: list[tuple[bytes, str]]
) -> str:
    ocr_texts = []
    for data, ext in images:
        image_text = await _ocr_image_bytes(data, ext)
        if image_text:
            ocr_texts.append(image_text)
    if not ocr_texts:
        return text
    return text + "\n" + "\n".join(ocr_texts)


async def _ocr_image_bytes(data: bytes, ext: str) -> str:
    if ext not in _CLOVA_NATIVE_FORMATS:
        # CLOVA가 지원하지 않는 포맷(bmp/gif 등)은 png로 변환해서 보낸다.
        buffer = io.BytesIO()
        Image.open(io.BytesIO(data)).convert("RGB").save(buffer, format="PNG")
        data = buffer.getvalue()
        ext = ".png"

    image_format = "jpg" if ext in (".jpg", ".jpeg") else ext.lstrip(".")
    return await call_clova_ocr_bytes(data, image_format, "embedded")

import asyncio
import io
import logging
from pathlib import Path

import pdfplumber
from PIL import Image
from pypdf import PdfReader

from app.core.config import get_settings
from app.ocr.clova_ocr_client import call_clova_ocr_bytes, fetch_clova_ocr_text
from app.ocr.hwp_loader import HWPLoader
from app.ocr.hwp_loader import extract_embedded_images as extract_hwp_images
from app.ocr.hwpx_loader import HWPXLoader
from app.ocr.hwpx_loader import extract_embedded_images as extract_hwpx_images

logger = logging.getLogger(__name__)

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
# 업로드 시 허용하는 확장자. extract_text가 실제로 처리할 수 있는 포맷과
# 동일하게 두어(단일 소스), 업로드는 됐는데 OCR 단계에서 못 여는 상황을 막는다.
SUPPORTED_UPLOAD_SUFFIXES = frozenset(_FILE_TYPE_BY_SUFFIX)

# pdfplumber/pypdf는 압축 스트림 처리에 크기·시간 제한이 없다(실측: 100KB
# 압축 폭탄으로 30초+ CPU 점유). 결과 크기를 제한할 방법이 없어 시간에 상한을 건다.
_PDF_EXTRACTION_TIMEOUT_SECONDS = 30


def file_type_for_suffix(suffix: str) -> str:
    """business_plan.file_type에 저장할 값 (예: ".jpg" -> "IMAGE").

    업로드 시점과 분석(extract_text 반환값) 시점이 같은 값 체계를 쓰도록
    단일 소스로 둔다. 예전에는 업로드가 확장자 대문자("JPG")를 저장했다가
    분석이 "IMAGE"로 덮어써 값이 어긋났다.
    """
    return _FILE_TYPE_BY_SUFFIX[suffix]


# CLOVA OCR이 그대로 받아주는 이미지 포맷 (bmp/gif 등은 여기 없으면 png로 변환)
_CLOVA_NATIVE_FORMATS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
# 임베드 이미지가 많으면 순차 처리 시 2분+ 걸려(실측 48개/122초) 동시에 보낸다.
# 동시 실행 제한은 call_clova_ocr_bytes의 전역 세마포어가 이미 처리한다.


async def extract_text(file_path: str) -> tuple[str, str]:
    """파일 확장자에 맞는 로더로 본문 텍스트를 추출한다.

    동기(CPU 바운드) 호출은 asyncio.to_thread로 감싼다 — 그대로 두면 서버
    전체가 멈춘다(이슈 #61). Returns: (추출된 텍스트, file_type).
    """
    suffix = Path(file_path).suffix.lower()
    if suffix not in _FILE_TYPE_BY_SUFFIX:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {suffix}")

    file_type = _FILE_TYPE_BY_SUFFIX[suffix]

    if suffix == ".hwp":
        text = await asyncio.to_thread(_load_hwp_text, file_path)
        images = await asyncio.to_thread(
            _extract_images_safely, extract_hwp_images, file_path
        )
        text = await _append_embedded_image_text(text, images)
    elif suffix == ".hwpx":
        text = await asyncio.to_thread(_load_hwpx_text, file_path)
        images = await asyncio.to_thread(
            _extract_images_safely, extract_hwpx_images, file_path
        )
        text = await _append_embedded_image_text(text, images)
    elif suffix == ".pdf":
        try:
            native_text = await asyncio.wait_for(
                asyncio.to_thread(_extract_native_pdf_text, file_path),
                timeout=_PDF_EXTRACTION_TIMEOUT_SECONDS,
            )
        except Exception:
            # 못 여는 파일(암호화·손상)이거나 시간 초과 시 빈 문자열로 두고 CLOVA로 넘어간다.
            native_text = ""
        if len(native_text) < get_settings().PDF_OCR_TEXT_THRESHOLD:
            # 네이티브 텍스트가 거의 없으면 스캔본으로 보고 페이지 전체를 CLOVA로 OCR한다.
            text = await fetch_clova_ocr_text(file_path)
        else:
            # 네이티브 텍스트가 있어도 그림으로 삽입된 차트·스크린샷은 텍스트로
            # 안 잡혀(실제 샘플 확인) 임베드 이미지를 보완 OCR한다.
            try:
                images = await asyncio.wait_for(
                    asyncio.to_thread(
                        _extract_images_safely, _extract_pdf_images, file_path
                    ),
                    timeout=_PDF_EXTRACTION_TIMEOUT_SECONDS,
                )
            except Exception:
                images = []
            text = await _append_embedded_image_text(native_text, images)
    else:
        text = await fetch_clova_ocr_text(file_path)

    # PostgreSQL은 text/varchar에 NUL(0x00) 바이트를 저장 못 해(실측 확인),
    # 모든 호출자에 영향을 주므로 반환 직전 한 곳에서 제거한다.
    text = text.replace("\x00", "")
    logger.info(
        "OCR 추출 완료 (file_path=%s, file_type=%s, 길이=%d자), 앞 50자: %s",
        file_path,
        file_type,
        len(text),
        text[:50],
    )
    return text, file_type


def _load_hwp_text(file_path: str) -> str:
    """HWPLoader로 HWP 본문 텍스트를 읽는다."""
    return HWPLoader(file_path).load()[0].page_content


def _load_hwpx_text(file_path: str) -> str:
    """HWPXLoader로 HWPX 본문 텍스트를 읽는다."""
    return HWPXLoader(file_path).load()[0].page_content


def _extract_images_safely(extractor, file_path: str) -> list[tuple[bytes, str]]:
    """임베드 이미지 추출기를 호출하되 실패해도 빈 리스트를 반환한다.

    이미지 추출이 실패해도 이미 확보한 본문 텍스트까지 잃으면 안 되므로 격리한다.
    """
    try:
        return extractor(file_path)
    except Exception:
        return []


def _extract_native_pdf_text(file_path: str) -> str:
    """PDF 자체에 이미 있는 텍스트 레이어를 읽는다.

    문서 프로그램으로 만든 PDF는 네이티브 텍스트가 OCR보다 정확해 이를 먼저 시도한다.
    pypdf 대신 pdfplumber를 쓰는 이유: 표 많은 문서에서 셀 순서를 더 안정적으로 보존함.
    """
    texts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            try:
                texts.append(page.extract_text() or "")
            except Exception:
                continue  # 한 페이지가 깨져 있어도 다른 페이지는 계속 뽑는다
    return "\n".join(texts)


def _extract_pdf_images(file_path: str) -> list[tuple[bytes, str]]:
    """PDF 안에 그림으로 삽입된 이미지를 전부 꺼낸다 (차트/스크린샷 등).

    HWP/HWPX의 extract_embedded_images와 같은 목적 — 네이티브 텍스트
    추출은 이미지 안의 글자를 못 읽으므로 별도로 OCR에 넘긴다.
    """
    reader = PdfReader(file_path)
    images = []
    for page in reader.pages:
        try:
            page_images = list(page.images)
        except Exception:
            continue  # 한 페이지 이미지 인코딩이 깨져도 다른 페이지는 계속 뽑는다
        for image in page_images:
            ext = (
                "." + image.name.rsplit(".", 1)[-1].lower() if "." in image.name else ""
            )
            images.append((image.data, ext))
    return images


async def _append_embedded_image_text(
    text: str, images: list[tuple[bytes, str]]
) -> str:
    """임베드 이미지들을 OCR해 본문 텍스트 뒤에 이어붙인다.

    같은 이미지(로고 등)가 반복 삽입되는 경우가 있어(실측: 39개 중 18개 중복)
    내용 기준 중복 제거 후 처리한다.
    """
    if not images:
        return text

    seen: set[bytes] = set()
    unique_images = []
    for data, ext in images:
        if data in seen:
            continue
        seen.add(data)
        unique_images.append((data, ext))
    images = unique_images

    async def _ocr_isolated(data: bytes, ext: str) -> str:
        """이미지 하나를 OCR하되 실패(NO_TEXT 등)해도 나머지 처리에 영향 없게 격리한다."""
        try:
            return await _ocr_image_bytes(data, ext)
        except Exception:
            return ""

    results = await asyncio.gather(*(_ocr_isolated(data, ext) for data, ext in images))
    ocr_texts = [t for t in results if t]
    if not ocr_texts:
        return text
    return text + "\n" + "\n".join(ocr_texts)


def _convert_to_png(data: bytes) -> bytes:
    """CLOVA가 지원하지 않는 이미지 포맷을 PNG 바이트로 변환한다."""
    buffer = io.BytesIO()
    Image.open(io.BytesIO(data)).convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


async def _ocr_image_bytes(data: bytes, ext: str) -> str:
    """이미지 바이트를 CLOVA가 인식하는 포맷으로 맞춰 OCR을 호출한다."""
    if ext not in _CLOVA_NATIVE_FORMATS:
        # CLOVA가 지원하지 않는 포맷(bmp/gif 등)은 png로 변환해서 보낸다.
        data = await asyncio.to_thread(_convert_to_png, data)
        ext = ".png"

    if ext in (".jpg", ".jpeg"):
        image_format = "jpg"
    elif ext == ".tif":
        # CLOVA는 "tiff"만 인식해 "tif"는 그대로 보내면 거부되고 텍스트가 유실된다
        # (pypdf가 CCITT 팩스 인코딩 이미지에 ".tif"를 붙이는 경우가 있음).
        image_format = "tiff"
    else:
        image_format = ext.lstrip(".")
    return await call_clova_ocr_bytes(data, image_format, "embedded")

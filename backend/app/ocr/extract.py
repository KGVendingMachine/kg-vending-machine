import asyncio
import io
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


def file_type_for_suffix(suffix: str) -> str:
    """business_plan.file_type에 저장할 값 (예: ".jpg" -> "IMAGE").

    업로드 시점과 분석(extract_text 반환값) 시점이 같은 값 체계를 쓰도록
    단일 소스로 둔다. 예전에는 업로드가 확장자 대문자("JPG")를 저장했다가
    분석이 "IMAGE"로 덮어써 값이 어긋났다.
    """
    return _FILE_TYPE_BY_SUFFIX[suffix]


# CLOVA OCR이 그대로 받아주는 이미지 포맷 (bmp/gif 등은 여기 없으면 png로 변환)
_CLOVA_NATIVE_FORMATS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
# 임베드 이미지가 많은 PDF(수십 개)에서 순차 처리하면 문서 하나에 2분 넘게
# 걸려서(실측: 이미지 48개, 122초) 동시에 여러 개씩 보낸다. 실제 동시
# 실행 개수 제한(계정 전체 기준 5개, 2026-07-11 실측)은
# clova_ocr_client.call_clova_ocr_bytes 안에서 전역으로 걸려있으므로
# 여기서는 그냥 다 동시에 요청해도 된다 — 초과분은 그쪽 세마포어에서
# 대기했다가 순서대로 실행된다. 문서 단위로 또 세마포어를 걸면(예: 여기
# 5개 + 배치로 공고 5개 동시) 계정 전체 한도를 오히려 넘기기 쉬워진다.


async def extract_text(file_path: str) -> tuple[str, str]:
    """파일 확장자에 맞는 로더로 본문 텍스트를 추출한다.

    HWP/HWPX는 문서 자체에 있는 텍스트를 로컬에서 바로 파싱하고, 거기에
    더해 문서 안에 그림으로 삽입된 표/차트(본문 텍스트로는 안 잡히는
    내용, 실제 샘플에서 확인함)도 CLOVA OCR로 인식해 뒤에 이어붙인다.
    PDF/이미지는 텍스트 레이어가 없다고 보고 CLOVA OCR을 호출한다.

    HWP/HWPX 파싱, PDF 네이티브 텍스트·이미지 추출, 이미지 포맷 변환은
    전부 동기(CPU 바운드) 호출이라 asyncio.to_thread로 감싼다 — 이 함수는
    FastAPI BackgroundTasks(요청과 같은 이벤트 루프)에서 실행되는데,
    동기 호출을 그대로 두면 파싱이 도는 동안 서버 전체(다른 요청)가
    멈춘다(실제로 겪음, 이슈 #61). CLOVA(httpx.AsyncClient)·LLM
    (AsyncOpenAI) 호출은 이미 비동기라 그대로 둔다.

    Returns:
        (추출된 텍스트, business_plan.file_type에 저장할 파일 유형)
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
            native_text = await asyncio.to_thread(_extract_native_pdf_text, file_path)
        except Exception:
            # PdfReader가 아예 못 여는 파일(암호화·손상 등)이면 빈 문자열로
            # 두고 아래 분기에서 CLOVA OCR로 넘어가게 한다.
            native_text = ""
        if len(native_text) < get_settings().PDF_OCR_TEXT_THRESHOLD:
            # 네이티브 텍스트가 거의 없으면 스캔본으로 보고 페이지 전체를
            # CLOVA로 OCR한다 (이 경우 임베드 이미지도 페이지 이미지에
            # 포함되어 이미 인식되므로 별도로 다시 돌리지 않는다).
            text = await fetch_clova_ocr_text(file_path)
        else:
            # 네이티브 텍스트는 있어도 본문에 그림으로 삽입된 차트·스크린샷은
            # 텍스트로 안 잡힌다 (실제 샘플에서 쿠팡 판매 스크린샷 확인함) —
            # HWP/HWPX와 동일하게 임베드 이미지를 보완 OCR한다.
            images = await asyncio.to_thread(
                _extract_images_safely, _extract_pdf_images, file_path
            )
            text = await _append_embedded_image_text(native_text, images)
    else:
        text = await fetch_clova_ocr_text(file_path)

    # PostgreSQL은 인코딩과 무관하게 text/varchar 컬럼에 NUL(0x00) 바이트를
    # 아예 저장하지 못한다(CharacterNotInRepertoireError). 실제 사업계획서
    # PDF 샘플에서 pdfplumber가 이 바이트를 뽑아내는 경우를 확인함(2026-07-11,
    # 공고 OCR 배치 트리거 테스트 중) — 이 함수 결과를 그대로 DB text
    # 컬럼에 저장하는 모든 호출자(공고 OCR, 사업계획서 분석)에 영향을
    # 주므로 반환 직전에 한 곳에서 제거한다.
    return text.replace("\x00", ""), file_type


def _load_hwp_text(file_path: str) -> str:
    return HWPLoader(file_path).load()[0].page_content


def _load_hwpx_text(file_path: str) -> str:
    return HWPXLoader(file_path).load()[0].page_content


def _extract_images_safely(extractor, file_path: str) -> list[tuple[bytes, str]]:
    """임베드 이미지 추출기를 호출하되, 실패해도 예외를 삼키고 빈 리스트를
    반환한다.

    HWP/HWPX/PDF 전부 이 함수 호출 전에 이미 본문 텍스트를 성공적으로
    뽑은 상태다. 뒤이은 임베드 이미지 추출(BinData 스트림 손상, 특수
    이미지 인코딩 등)이 실패한다고 해서 이미 확보한 본문 텍스트까지
    잃으면 안 되므로, 여기서 실패를 격리한다.
    """
    try:
        return extractor(file_path)
    except Exception:
        return []


def _extract_native_pdf_text(file_path: str) -> str:
    """PDF 자체에 이미 있는 텍스트 레이어를 읽는다.

    실제 사업계획서 샘플로 확인해보니, 스캔본이 아니라 문서 프로그램에서
    바로 만든 PDF가 많았고 이 경우 CLOVA OCR보다 네이티브 텍스트가 더
    많고 정확했다 (OCR 인식 오류/누락이 없어서). 그래서 PDF는 OCR을
    기본값으로 두지 않고, 네이티브 텍스트를 먼저 시도한다.

    pypdf 대신 pdfplumber를 쓰는 이유: 표가 많은 사업계획서 양식에서
    pypdf가 셀 순서를 뒤섞어 뽑는 경우가 실제 샘플에서 확인됐고(예:
    "최대 1. 이내 10page 로"처럼 번호와 본문이 엇갈림), pdfplumber가
    읽기 순서를 더 안정적으로 보존했다.
    """
    texts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            try:
                texts.append(page.extract_text() or "")
            except Exception:
                # 한 페이지의 폰트/콘텐츠 스트림이 깨져 있어도 다른 페이지
                # 텍스트는 계속 뽑는다 (페이지 하나 때문에 전체를 포기하지 않음).
                continue
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
            # 한 페이지의 이미지 인코딩이 이상해도 다른 페이지 이미지는
            # 계속 뽑는다 (페이지 하나 때문에 전체를 포기하지 않음).
            continue
        for image in page_images:
            ext = (
                "." + image.name.rsplit(".", 1)[-1].lower() if "." in image.name else ""
            )
            images.append((image.data, ext))
    return images


async def _append_embedded_image_text(
    text: str, images: list[tuple[bytes, str]]
) -> str:
    if not images:
        return text

    # 같은 이미지(로고·워터마크 등)가 여러 페이지에 반복 삽입된 경우가
    # 실제로 있었다 (샘플 하나는 39개 중 18개가 중복). 같은 이미지를
    # 중복으로 OCR 돌리면 API 호출도 낭비고 같은 텍스트가 결과에
    # 여러 번 섞여 들어간다 — 내용 기준으로 중복 제거 후 처리한다.
    seen: set[bytes] = set()
    unique_images = []
    for data, ext in images:
        if data in seen:
            continue
        seen.add(data)
        unique_images.append((data, ext))
    images = unique_images

    async def _ocr_isolated(data: bytes, ext: str) -> str:
        try:
            return await _ocr_image_bytes(data, ext)
        except Exception:
            # 로고·아이콘처럼 글자가 없는 이미지는 CLOVA가 NO_TEXT
            # 오류를 낸다. 이미지 하나가 실패해도 나머지 이미지
            # 처리가 전부 죽지 않도록 항목별로 격리한다.
            return ""

    results = await asyncio.gather(*(_ocr_isolated(data, ext) for data, ext in images))
    ocr_texts = [t for t in results if t]
    if not ocr_texts:
        return text
    return text + "\n" + "\n".join(ocr_texts)


def _convert_to_png(data: bytes) -> bytes:
    buffer = io.BytesIO()
    Image.open(io.BytesIO(data)).convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


async def _ocr_image_bytes(data: bytes, ext: str) -> str:
    if ext not in _CLOVA_NATIVE_FORMATS:
        # CLOVA가 지원하지 않는 포맷(bmp/gif 등)은 png로 변환해서 보낸다.
        data = await asyncio.to_thread(_convert_to_png, data)
        ext = ".png"

    if ext in (".jpg", ".jpeg"):
        image_format = "jpg"
    elif ext == ".tif":
        # CLOVA는 "tiff"만 인식하고 "tif"는 모른다 (clova_ocr_client의
        # _SUPPORTED_FORMATS 참고). pypdf가 CCITT 팩스 인코딩 이미지(스캔된
        # 관공서 문서의 도장·서명 등에서 흔함)에 ".tif"를 붙이는 경우가
        # 있어, 그대로 보내면 CLOVA가 거부하고 해당 이미지 텍스트만
        # 조용히 유실된다.
        image_format = "tiff"
    else:
        image_format = ext.lstrip(".")
    return await call_clova_ocr_bytes(data, image_format, "embedded")

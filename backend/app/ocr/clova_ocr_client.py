import asyncio
import base64
import io
import time
import uuid
from pathlib import Path

import httpx
from pypdf import PdfReader, PdfWriter

from app.core.config import get_settings

_SUPPORTED_FORMATS = {
    ".pdf": "pdf",
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".png": "png",
    ".tiff": "tiff",
}
# CLOVA 일반 OCR API 자체 제한 (실제 호출로 확인: 11페이지 이상 PDF는
# "Request invalid: No more than 10 pages." 오류를 반환함).
_CLOVA_MAX_PDF_PAGES = 10


async def fetch_clova_ocr_text(file_path: str) -> str:
    """Naver CLOVA OCR(General)로 문서(PDF/이미지)에서 텍스트를 추출한다.

    CLOVA 일반 OCR은 PDF를 이미지로 직접 변환하지 않고 그대로 base64로
    보내면 내부적으로 페이지를 인식한다 (별도 pdf2image 변환 불필요).
    다만 한 번 요청에 10페이지를 넘는 PDF는 거부되므로, 그보다 길면
    10페이지 단위로 나눠 여러 번 호출한 뒤 순서대로 이어붙인다.
    """
    suffix = Path(file_path).suffix.lower()
    if suffix not in _SUPPORTED_FORMATS:
        raise ValueError(f"CLOVA OCR이 지원하지 않는 확장자입니다: {suffix}")

    if suffix != ".pdf":
        with open(file_path, "rb") as f:
            return await call_clova_ocr_bytes(
                f.read(), _SUPPORTED_FORMATS[suffix], Path(file_path).stem
            )

    reader = PdfReader(file_path)
    chunks = [
        reader.pages[i : i + _CLOVA_MAX_PDF_PAGES]
        for i in range(0, len(reader.pages), _CLOVA_MAX_PDF_PAGES)
    ]

    texts = []
    for chunk_pages in chunks:
        writer = PdfWriter()
        for page in chunk_pages:
            writer.add_page(page)
        buffer = io.BytesIO()
        writer.write(buffer)
        texts.append(
            await call_clova_ocr_bytes(buffer.getvalue(), "pdf", Path(file_path).stem)
        )

    return "\n".join(texts)


async def call_clova_ocr_bytes(file_bytes: bytes, image_format: str, name: str) -> str:
    settings = get_settings()
    request_body = {
        "version": "V2",
        "requestId": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
        "lang": settings.CLOVA_OCR_LANGUAGE,
        "images": [
            {
                "format": image_format,
                "name": name,
                "data": base64.b64encode(file_bytes).decode("utf-8"),
            }
        ],
    }
    headers = {
        "X-OCR-SECRET": settings.CLOVA_OCR_SECRET_KEY,
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=settings.CLOVA_OCR_TIMEOUT_SECONDS) as client:
        for attempt in range(1, settings.CLOVA_OCR_MAX_RETRIES + 1):
            try:
                response = await client.post(
                    settings.CLOVA_OCR_INVOKE_URL, json=request_body, headers=headers
                )
                response.raise_for_status()
                payload = response.json()
                images = payload.get("images")
                if not images:
                    raise RuntimeError(f"CLOVA OCR이 오류를 반환했습니다: {payload}")
                # 여러 페이지 PDF를 한 번에 보내면 페이지마다 images 배열에
                # 항목이 하나씩 생겨서 돌아온다 (page 1개 = images 1개가
                # 아님). images[0]만 읽으면 첫 페이지 텍스트만 남고 나머지
                # 페이지가 조용히 유실되므로 전체를 순회해야 한다.
                page_texts = []
                for image in images:
                    if image.get("inferResult") != "SUCCESS":
                        raise RuntimeError(
                            f"CLOVA OCR이 오류를 반환했습니다: {payload}"
                        )
                    page_texts.append(_fields_to_text(image.get("fields", [])))
                return "\n".join(page_texts)
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt < settings.CLOVA_OCR_MAX_RETRIES:
                    await asyncio.sleep(attempt)

    raise RuntimeError(
        f"CLOVA OCR 요청이 {settings.CLOVA_OCR_MAX_RETRIES}회 모두 실패했습니다"
    ) from last_error


def _fields_to_text(fields: list[dict]) -> str:
    """CLOVA 응답의 fields(단어/토큰 단위)를 사람이 읽을 문단 형태로 합친다.

    lineBreak=True인 필드 뒤에서 줄을 바꾸고, 아니면 공백으로 이어붙인다
    (CLOVA가 줄 끝 토큰에 lineBreak를 표시해주는 것을 그대로 따름).
    """
    parts = []
    for field in fields:
        # get(..., "")은 키가 아예 없을 때만 기본값을 쓰므로, "inferText": null처럼
        # 키는 있고 값이 None인 경우까지 막으려면 or ""로 한 번 더 감싸야 한다.
        parts.append(field.get("inferText") or "")
        parts.append("\n" if field.get("lineBreak") else " ")
    return "".join(parts).strip()

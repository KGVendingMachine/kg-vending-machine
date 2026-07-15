import asyncio

import httpx
from bs4 import BeautifulSoup

from app.core.config import get_settings

_DETAIL_PAGE_URL = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
_BASE_URL = "https://www.k-startup.go.kr"


async def fetch_kstartup_attachments(pbanc_sn: int) -> list[tuple[str, str]]:
    """K-Startup 공고 상세페이지에서 첨부파일 (파일명, 다운로드 URL) 목록을 가져온다.

    목록 API 응답에는 첨부파일 정보가 없어(실측 확인) 상세페이지 HTML을 파싱한다.
    """
    settings = get_settings()
    params = {"schM": "view", "pbancSn": pbanc_sn}

    last_error: Exception | None = None
    async with httpx.AsyncClient(
        timeout=settings.KSTARTUP_REQUEST_TIMEOUT_SECONDS
    ) as client:
        for attempt in range(1, settings.KSTARTUP_MAX_RETRIES + 1):
            try:
                response = await client.get(_DETAIL_PAGE_URL, params=params)
                response.raise_for_status()
                return _parse_attachments(response.text)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < settings.KSTARTUP_MAX_RETRIES:
                    await asyncio.sleep(attempt)

    raise RuntimeError(
        f"K-Startup 상세페이지 요청이 {settings.KSTARTUP_MAX_RETRIES}회 모두 실패했습니다"
    ) from last_error


def _parse_attachments(html: str) -> list[tuple[str, str]]:
    """상세페이지 HTML에서 a.file_bg 링크들을 (파일명, 절대 URL)로 파싱한다."""
    soup = BeautifulSoup(html, "html.parser")
    attachments = []
    for file_link in soup.select("a.file_bg"):
        file_name = file_link.get("title", "").removeprefix("[첨부파일] ")
        li = file_link.find_parent("li")
        download_link = li.select_one("a.btn_down") if li else None
        href = download_link.get("href") if download_link else None
        if not file_name or not href:
            continue
        attachments.append((file_name, _BASE_URL + href))
    return attachments


# 서버가 예상외로 큰 파일을 내려줄 경우에 대비한 안전장치(응답 전체를
# 메모리에 올리는 압축 해제 폭탄류 문제 방지). 실제 첨부파일은 이 크기를 넘지 않음.
_MAX_ATTACHMENT_SIZE_BYTES = 100 * 1024 * 1024


async def _read_response_with_size_limit(
    response: httpx.Response, source: str
) -> bytes:
    """응답 바디를 스트리밍으로 읽되 크기 제한을 넘으면 중단한다.

    response.content를 바로 쓰지 않는 이유: 크기 제한 없이 전체를 메모리에 올리기 때문.
    """
    chunks = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > _MAX_ATTACHMENT_SIZE_BYTES:
            raise RuntimeError(
                f"첨부파일이 허용 크기({_MAX_ATTACHMENT_SIZE_BYTES} bytes)를 "
                f"초과했습니다: {source}"
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def download_kstartup_attachment(file_url: str) -> bytes:
    """fetch_kstartup_attachments가 반환한 다운로드 URL로 실제 파일을 받는다.

    별도 로그인/세션 없이 GET 한 번으로 파일이 내려온다 (%PDF 매직바이트로 검증함).
    """
    settings = get_settings()
    last_error: Exception | None = None
    async with httpx.AsyncClient(
        timeout=settings.KSTARTUP_REQUEST_TIMEOUT_SECONDS
    ) as client:
        for attempt in range(1, settings.KSTARTUP_MAX_RETRIES + 1):
            try:
                async with client.stream("GET", file_url) as response:
                    response.raise_for_status()
                    return await _read_response_with_size_limit(response, file_url)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < settings.KSTARTUP_MAX_RETRIES:
                    await asyncio.sleep(attempt)

    raise RuntimeError(
        f"K-Startup 첨부파일 다운로드가 {settings.KSTARTUP_MAX_RETRIES}회 모두 실패했습니다"
    ) from last_error

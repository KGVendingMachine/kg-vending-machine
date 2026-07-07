import asyncio

import httpx
from bs4 import BeautifulSoup

from app.core.config import get_settings

_DETAIL_PAGE_URL = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
_BASE_URL = "https://www.k-startup.go.kr"


async def fetch_kstartup_attachments(pbanc_sn: int) -> list[tuple[str, str]]:
    """K-Startup 공고 상세페이지에서 첨부파일 (파일명, 다운로드 URL) 목록을 가져온다.

    K-Startup 목록 API 응답에는 첨부파일 정보가 없다 (전체 29,353건 실제
    확인함). 상세페이지 HTML을 열어보면 자바스크립트 렌더링 없이도 서버가
    이미 첨부파일 링크(/afile/fileDownload/{코드})를 내려주는 것을 실제
    호출로 확인해, 헤드리스 브라우저 없이 httpx + BeautifulSoup만으로
    처리한다.

    전체 공고를 미리 다 훑지 않고, 매칭 후보로 좁혀진 공고에 대해서만
    필요할 때 단건으로 호출하는 용도다 (docs/matching-pipeline.md 4단계).
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
    soup = BeautifulSoup(html, "html.parser")
    attachments = []
    for file_link in soup.select("a.file_bg"):
        file_name = file_link.get("title", "").removeprefix("[첨부파일] ")
        li = file_link.find_parent("li")
        download_link = li.select_one("a.btn_down") if li else None
        if not file_name or download_link is None:
            continue
        attachments.append((file_name, _BASE_URL + download_link["href"]))
    return attachments


async def download_kstartup_attachment(file_url: str) -> bytes:
    """fetch_kstartup_attachments가 반환한 다운로드 URL로 실제 파일을 받는다.

    별도 로그인/세션 없이 GET 한 번으로 파일이 내려오는 것을 실제
    호출로 확인함 (%PDF 매직바이트 검증).
    """
    settings = get_settings()
    last_error: Exception | None = None
    async with httpx.AsyncClient(
        timeout=settings.KSTARTUP_REQUEST_TIMEOUT_SECONDS
    ) as client:
        for attempt in range(1, settings.KSTARTUP_MAX_RETRIES + 1):
            try:
                response = await client.get(file_url)
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < settings.KSTARTUP_MAX_RETRIES:
                    await asyncio.sleep(attempt)

    raise RuntimeError(
        f"K-Startup 첨부파일 다운로드가 {settings.KSTARTUP_MAX_RETRIES}회 모두 실패했습니다"
    ) from last_error

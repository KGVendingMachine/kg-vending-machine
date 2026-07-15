import asyncio

import httpx

from app.core.config import get_settings

# bizinfo_client.py의 _MAX_ATTACHMENT_SIZE_BYTES와 같은 이유 - 서버가
# 예상외로 큰 파일을 내려주는 경우에 대비한 안전장치.
_MAX_ATTACHMENT_SIZE_BYTES = 100 * 1024 * 1024


async def fetch_msit_notices(page: int = 1) -> list[dict]:
    """과학기술정보통신부 사업공고 API에서 공고 목록 원본 응답을 가져온다.

    문서와 달리 http는 400을 반환해 https + User-Agent 헤더가 필요함(2026-07-13 실측).
    """
    settings = get_settings()
    params = {
        "ServiceKey": settings.MSIT_API_KEY,
        "pageNo": page,
        "numOfRows": settings.MSIT_PAGE_SIZE,
        "returnType": "json",
    }
    # data.go.kr 게이트웨이가 User-Agent 없는 요청을 차단하는 것을 실측으로
    # 확인함(2026-07-13) - curl 기본 User-Agent로도 400이 났었다.
    headers = {"User-Agent": "Mozilla/5.0"}

    last_error: Exception | None = None
    async with httpx.AsyncClient(
        timeout=settings.MSIT_REQUEST_TIMEOUT_SECONDS
    ) as client:
        for attempt in range(1, settings.MSIT_MAX_RETRIES + 1):
            try:
                response = await client.get(
                    settings.MSIT_API_URL, params=params, headers=headers
                )
                response.raise_for_status()
                payload = response.json()
                items = _extract_items(payload)
                return items
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt < settings.MSIT_MAX_RETRIES:
                    await asyncio.sleep(attempt)

    raise RuntimeError(
        f"과학기술정보통신부 사업공고 API 요청이 {settings.MSIT_MAX_RETRIES}회 모두 실패했습니다"
    ) from last_error


def _extract_items(payload: dict) -> list[dict]:
    """response -> [header, body] -> body.items -> [{"item": {...}}] 구조를 평탄화한다.

    각 item의 files도 [{"file": {...}}] -> [{...}]로 같이 풀어준다.
    """
    try:
        sections = payload["response"]
        header = next(s["header"] for s in sections if "header" in s)
        body = next(s["body"] for s in sections if "body" in s)
    except (KeyError, StopIteration, TypeError) as exc:
        raise RuntimeError(
            f"과학기술정보통신부 API가 예상과 다른 구조를 반환했습니다: {payload}"
        ) from exc

    if header.get("resultCode") != "00":
        raise RuntimeError(f"과학기술정보통신부 API가 오류를 반환했습니다: {header}")

    raw_items = body.get("items") or []
    items: list[dict] = []
    for wrapped in raw_items:
        item = wrapped.get("item") if isinstance(wrapped, dict) else None
        if item is None:
            continue
        raw_files = item.get("files") or []
        item = {
            **item,
            "files": [
                f["file"] for f in raw_files if isinstance(f, dict) and "file" in f
            ],
        }
        items.append(item)
    return items


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


async def download_msit_attachment(file_url: str) -> bytes:
    """과학기술정보통신부 첨부파일 URL(msit.go.kr/ssm/file/fileDown.do?...)에서 실제 파일을 받는다.

    목록 API 응답에 다운로드 URL이 바로 들어있어 상세페이지를 열 필요가 없다.
    """
    settings = get_settings()
    headers = {"User-Agent": "Mozilla/5.0"}
    last_error: Exception | None = None
    async with httpx.AsyncClient(
        timeout=settings.MSIT_REQUEST_TIMEOUT_SECONDS
    ) as client:
        for attempt in range(1, settings.MSIT_MAX_RETRIES + 1):
            try:
                async with client.stream(
                    "GET", file_url, headers=headers, follow_redirects=True
                ) as response:
                    response.raise_for_status()
                    return await _read_response_with_size_limit(response, file_url)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < settings.MSIT_MAX_RETRIES:
                    await asyncio.sleep(attempt)

    raise RuntimeError(
        f"과학기술정보통신부 첨부파일 다운로드가 {settings.MSIT_MAX_RETRIES}회 모두 실패했습니다"
    ) from last_error

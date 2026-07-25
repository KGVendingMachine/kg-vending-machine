import asyncio

import httpx

from app.core.config import get_settings


async def _fetch_bizinfo_page(extra_params: dict) -> list[dict]:
    """기업마당(bizinfoApi.do) 원본 응답을 가져온다 (공통 재시도 로직).

    공공 API가 간헐적으로 5xx/timeout을 반환할 수 있어 즉시 실패시키지 않고 재시도한다.
    """
    settings = get_settings()
    params = {
        "crtfcKey": settings.BIZINFO_API_KEY,
        "dataType": "json",
        **extra_params,
    }

    last_error: Exception | None = None
    # 재시도마다 커넥션을 새로 맺지 않도록 AsyncClient(커넥션 풀)를
    # 재시도 루프 밖에서 한 번만 만들어 재사용한다.
    async with httpx.AsyncClient(
        timeout=settings.BIZINFO_REQUEST_TIMEOUT_SECONDS
    ) as client:
        for attempt in range(1, settings.BIZINFO_MAX_RETRIES + 1):
            try:
                response = await client.get(settings.BIZINFO_API_URL, params=params)
                response.raise_for_status()
                payload = response.json()
                # HTTP 200이어도 파라미터가 잘못되면 {"reqErr": "..."}를 줄 수 있어
                # jsonArray 없는 응답을 "공고 0개"로 오인하지 않도록 에러 처리한다.
                if "jsonArray" not in payload:
                    raise RuntimeError(f"BizInfo API가 오류를 반환했습니다: {payload}")
                items = payload["jsonArray"]
                if not isinstance(items, list):
                    raise RuntimeError(
                        f"BizInfo API 응답의 jsonArray가 list가 아닙니다: {type(items).__name__}"
                    )
                return items
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt < settings.BIZINFO_MAX_RETRIES:
                    await asyncio.sleep(attempt)

    raise RuntimeError(
        f"BizInfo API 요청이 {settings.BIZINFO_MAX_RETRIES}회 모두 실패했습니다"
    ) from last_error


async def fetch_bizinfo_notices(page: int = 1) -> list[dict]:
    """기업마당(bizinfoApi.do)에서 공고 목록 원본 응답을 가져온다.

    pageUnit+pageIndex 조합이 실제 페이징 파라미터다(searchCnt 단독으로는 페이지 이동 안 됨).
    """
    settings = get_settings()
    return await _fetch_bizinfo_page(
        {"pageUnit": settings.BIZINFO_PAGE_SIZE, "pageIndex": page}
    )


async def fetch_bizinfo_notice_by_id(pblanc_id: str) -> dict | None:
    """기업마당 공고 하나를 pblancId로 단건 조회한다 (단건 재수집용).

    pblancId 필터가 실제로 동작해(totCnt=1) 페이지를 훑지 않고 바로 가져올 수 있다.
    """
    items = await _fetch_bizinfo_page(
        {"pageUnit": 10, "pageIndex": 1, "pblancId": pblanc_id}
    )
    return items[0] if items else None


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


async def download_bizinfo_attachment(file_url: str) -> bytes:
    """기업마당 첨부파일 URL(getImageFile.do?...)에서 실제 파일을 받는다.

    목록 API 응답에 다운로드 URL이 바로 들어있어 상세페이지를 열 필요가 없다.
    """
    settings = get_settings()
    last_error: Exception | None = None
    async with httpx.AsyncClient(
        timeout=settings.BIZINFO_REQUEST_TIMEOUT_SECONDS
    ) as client:
        for attempt in range(1, settings.BIZINFO_MAX_RETRIES + 1):
            try:
                async with client.stream(
                    "GET", file_url, follow_redirects=True
                ) as response:
                    response.raise_for_status()
                    return await _read_response_with_size_limit(response, file_url)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < settings.BIZINFO_MAX_RETRIES:
                    await asyncio.sleep(attempt)

    raise RuntimeError(
        f"기업마당 첨부파일 다운로드가 {settings.BIZINFO_MAX_RETRIES}회 모두 실패했습니다"
    ) from last_error

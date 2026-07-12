import asyncio

import httpx

from app.core.config import get_settings


async def fetch_bizinfo_notices(page: int = 1) -> list[dict]:
    """기업마당(bizinfoApi.do)에서 공고 목록 원본 응답을 가져온다.

    응답 실패 시 settings.BIZINFO_MAX_RETRIES만큼 재시도한다(공공 API가
    간헐적으로 5xx/timeout을 반환하는 경우가 있어 즉시 실패시키지 않음).
    """
    settings = get_settings()
    # pageUnit(페이지당 개수) + pageIndex(페이지 번호) 조합이 실제 페이징
    # 파라미터다. searchCnt만 단독으로 쓰면 페이지 이동 없이 항상 첫
    # 페이지만 반환되고, pageIndex를 searchCnt와 같이 보내면 API가
    # "한 페이지의 보여지는 데이터 개수를 입력해주세요" 에러를 반환한다
    # (실제 호출로 확인함, 공식 문서에 명확히 없음).
    params = {
        "crtfcKey": settings.BIZINFO_API_KEY,
        "dataType": "json",
        "pageUnit": settings.BIZINFO_PAGE_SIZE,
        "pageIndex": page,
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
                # HTTP 200이어도 요청 파라미터가 잘못되면 {"reqErr": "..."}
                # 같은 오류 응답을 줄 수 있다(실제로 겪음). jsonArray가 없는
                # 응답을 "공고 0개"로 오인하지 않도록 명시적으로 에러 처리한다.
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


# 기업마당 서버가 예상외로 큰 파일을 내려주는 경우(오설정·오류 응답 등)에
# 대비한 안전장치. response.content로 그냥 받으면 크기 제한 없이 응답
# 전체를 메모리에 올리는데, 배치 OCR 트리거로 여러 첨부파일을 동시에
# 다운로드할 때 이게 겹치면 서버 메모리를 위협할 수 있다(HWP/HWPX/PDF
# 압축 해제 폭탄과 같은 종류의 문제). 실제 공고 첨부파일은 이 크기를
# 넘는 경우가 없다고 보고 넉넉하게 잡은 값.
_MAX_ATTACHMENT_SIZE_BYTES = 100 * 1024 * 1024


async def _read_response_with_size_limit(
    response: httpx.Response, source: str
) -> bytes:
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

    기업마당은 목록 API 응답에 다운로드 URL이 바로 들어있어(K-Startup처럼
    상세페이지를 열 필요 없음), URL만 있으면 바로 GET으로 받아온다.
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

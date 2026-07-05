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
                return payload.get("jsonArray", [])
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < settings.BIZINFO_MAX_RETRIES:
                    await asyncio.sleep(attempt)

    raise RuntimeError(
        f"BizInfo API 요청이 {settings.BIZINFO_MAX_RETRIES}회 모두 실패했습니다"
    ) from last_error

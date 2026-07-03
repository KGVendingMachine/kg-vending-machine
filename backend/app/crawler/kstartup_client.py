import asyncio

import httpx

from app.core.config import get_settings


async def fetch_kstartup_notices(page: int = 1) -> list[dict]:
    """K-Startup(data.go.kr) 공고 목록 원본 응답을 가져온다.

    응답 실패 시 settings.KSTARTUP_MAX_RETRIES만큼 재시도한다.
    """
    settings = get_settings()
    params = {
        "serviceKey": settings.KSTARTUP_API_KEY,
        "page": page,
        "perPage": settings.KSTARTUP_PAGE_SIZE,
        "returnType": "json",
    }

    last_error: Exception | None = None
    for attempt in range(1, settings.KSTARTUP_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=settings.KSTARTUP_REQUEST_TIMEOUT_SECONDS
            ) as client:
                response = await client.get(settings.KSTARTUP_API_URL, params=params)
                response.raise_for_status()
                payload = response.json()
                return payload.get("data", [])
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt < settings.KSTARTUP_MAX_RETRIES:
                await asyncio.sleep(attempt)

    raise RuntimeError(
        f"K-Startup API 요청이 {settings.KSTARTUP_MAX_RETRIES}회 모두 실패했습니다"
    ) from last_error

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
    # 재시도마다 커넥션을 새로 맺지 않도록 AsyncClient(커넥션 풀)를
    # 재시도 루프 밖에서 한 번만 만들어 재사용한다.
    async with httpx.AsyncClient(
        timeout=settings.KSTARTUP_REQUEST_TIMEOUT_SECONDS
    ) as client:
        for attempt in range(1, settings.KSTARTUP_MAX_RETRIES + 1):
            try:
                response = await client.get(settings.KSTARTUP_API_URL, params=params)
                response.raise_for_status()
                payload = response.json()
                # HTTP 200이어도 오류 응답을 줄 수 있어, data가 없는 응답을
                # "공고 0개"로 오인하지 않도록 명시적으로 에러 처리한다.
                if "data" not in payload:
                    raise RuntimeError(f"K-Startup API가 오류를 반환했습니다: {payload}")
                items = payload["data"]
                if not isinstance(items, list):
                    raise RuntimeError(
                        f"K-Startup API 응답의 data가 list가 아닙니다: {type(items).__name__}"
                    )
                return items
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < settings.KSTARTUP_MAX_RETRIES:
                    await asyncio.sleep(attempt)

    raise RuntimeError(
        f"K-Startup API 요청이 {settings.KSTARTUP_MAX_RETRIES}회 모두 실패했습니다"
    ) from last_error

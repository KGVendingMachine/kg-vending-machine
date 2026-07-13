"""카카오 OAuth2 HTTP 호출.

인가 코드(code)를 카카오 access_token으로 교환하고, 그 토큰으로 사용자
정보를 조회한다. 이 카카오 토큰은 신원 확인 용도로만 쓰고 저장하지 않으며,
서비스 인증은 별도로 발급하는 자체 JWT가 담당한다.
"""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class KakaoAuthError(Exception):
    """카카오 인증 과정에서의 오류. 라우터에서 401/400으로 변환한다."""


async def exchange_code_for_token(code: str) -> str:
    """인가 코드를 카카오 access_token으로 교환한다.

    인가 코드는 일회용이라 실패해도 재시도하지 않는다(이미 소비됐을 수 있어
    재시도가 오히려 혼란을 준다). client_secret은 설정된 경우에만 보낸다.
    """
    settings = get_settings()
    data = {
        "grant_type": "authorization_code",
        "client_id": settings.KAKAO_CLIENT_ID,
        "redirect_uri": settings.KAKAO_REDIRECT_URI,
        "code": code,
    }
    if settings.KAKAO_CLIENT_SECRET:
        data["client_secret"] = settings.KAKAO_CLIENT_SECRET

    async with httpx.AsyncClient(
        timeout=settings.KAKAO_REQUEST_TIMEOUT_SECONDS
    ) as client:
        try:
            response = await client.post(settings.KAKAO_TOKEN_URL, data=data)
        except httpx.HTTPError as exc:
            raise KakaoAuthError(f"카카오 토큰 요청 실패: {exc}") from exc

    if response.status_code != 200:
        raise KakaoAuthError(
            f"카카오 토큰 교환이 거부되었습니다({response.status_code}): {response.text}"
        )

    access_token = response.json().get("access_token")
    if not access_token:
        raise KakaoAuthError("카카오 응답에 access_token이 없습니다")
    return access_token


async def fetch_kakao_user(access_token: str) -> dict:
    """카카오 access_token으로 사용자 정보(회원번호/이메일/프로필)를 조회한다."""
    settings = get_settings()
    async with httpx.AsyncClient(
        timeout=settings.KAKAO_REQUEST_TIMEOUT_SECONDS
    ) as client:
        try:
            response = await client.get(
                settings.KAKAO_USER_INFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.HTTPError as exc:
            raise KakaoAuthError(f"카카오 사용자 정보 요청 실패: {exc}") from exc

    if response.status_code != 200:
        raise KakaoAuthError(
            f"카카오 사용자 정보 조회 실패({response.status_code}): {response.text}"
        )
    return response.json()


async def unlink_user(kakao_id: str) -> None:
    """회원탈퇴 시 카카오 계정과 앱의 연결을 끊는다(Admin 키 방식).

    로그인 때 받은 카카오 토큰은 저장하지 않으므로, 서버가 보관하는
    Admin 키 + 회원번호(target_id)로 호출한다. Admin 키가 설정되지 않은
    환경(로컬 개발)에서는 건너뛴다. 실패 시 KakaoAuthError를 던져 호출자가
    탈퇴를 중단(재시도 가능)할 수 있게 한다.
    """
    settings = get_settings()
    if not settings.KAKAO_ADMIN_KEY:
        logger.warning("KAKAO_ADMIN_KEY 미설정 - 카카오 unlink를 건너뜁니다")
        return

    async with httpx.AsyncClient(
        timeout=settings.KAKAO_REQUEST_TIMEOUT_SECONDS
    ) as client:
        try:
            response = await client.post(
                settings.KAKAO_UNLINK_URL,
                headers={"Authorization": f"KakaoAK {settings.KAKAO_ADMIN_KEY}"},
                data={"target_id_type": "user_id", "target_id": kakao_id},
            )
        except httpx.HTTPError as exc:
            raise KakaoAuthError(f"카카오 연결 끊기 요청 실패: {exc}") from exc

    if response.status_code != 200:
        raise KakaoAuthError(
            f"카카오 연결 끊기 실패({response.status_code}): {response.text}"
        )

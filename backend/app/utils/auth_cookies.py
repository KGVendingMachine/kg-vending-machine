"""인증 쿠키의 이름과 설정을 한곳에서 관리한다.

access/refresh 토큰은 httpOnly 쿠키로 심어 브라우저가 요청마다 자동으로
실어 보내게 한다(JS로는 읽지 못해 XSS로부터 토큰을 보호한다). 라우터(auth)와
의존성(deps)이 같은 쿠키 이름·속성을 써야 하므로 여기에 모아둔다.

로컬은 프론트(5173)와 백엔드(8000)가 same-site(포트만 다름)라 SameSite=Lax로도
fetch에 자동 전송된다. 운영에서 도메인이 갈리면 SameSite=None; Secure로 바꿔야 한다.
"""

from fastapi import Response

from app.core.config import get_settings

ACCESS_TOKEN_COOKIE_NAME = "access_token"
REFRESH_TOKEN_COOKIE_NAME = "refresh_token"

# 삭제 시에도 동일하게 맞춰야 브라우저가 같은 쿠키로 인식해 지운다.
_COOKIE_PATH = "/"
_COOKIE_KWARGS = {"httponly": True, "samesite": "lax", "path": _COOKIE_PATH}


def set_access_cookie(response: Response, token: str) -> None:
    """access token을 httpOnly 쿠키로 심는다(만료는 access 토큰 수명과 동일)."""
    settings = get_settings()
    response.set_cookie(
        ACCESS_TOKEN_COOKIE_NAME,
        token,
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **_COOKIE_KWARGS,
    )


def set_refresh_cookie(response: Response, token: str) -> None:
    """refresh token을 httpOnly 쿠키로 심는다(만료는 refresh 토큰 수명과 동일)."""
    settings = get_settings()
    response.set_cookie(
        REFRESH_TOKEN_COOKIE_NAME,
        token,
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        **_COOKIE_KWARGS,
    )


def clear_auth_cookies(response: Response) -> None:
    """access/refresh 쿠키를 삭제한다(Set-Cookie Max-Age=0).

    httpOnly 쿠키는 JS로 지울 수 없어 로그아웃은 서버가 만료시켜야 한다.
    """
    response.delete_cookie(ACCESS_TOKEN_COOKIE_NAME, path=_COOKIE_PATH)
    response.delete_cookie(REFRESH_TOKEN_COOKIE_NAME, path=_COOKIE_PATH)

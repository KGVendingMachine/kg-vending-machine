"""인증 라우터.

HTTP 입출력과 예외 변환만 담당하고 비즈니스 로직은 서비스에 위임한다.
"""

import secrets
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.auth import (
    AccessTokenResponse,
    KakaoLoginRequest,
    RefreshRequest,
    TokenResponse,
)
from app.services.auth_service import (
    InactiveAccountError,
    RefreshTokenError,
    login_with_kakao,
    refresh_access_token,
)
from app.utils.kakao_client import KakaoAuthError

router = APIRouter()

STATE_COOKIE_NAME = "kakao_oauth_state"
"""로그인 시작과 콜백 사이에서 CSRF 방지용 state·모드를 대조하기 위한 쿠키.

값은 "{mode}:{state}" 형태. mode가 "code"면 콜백이 로그인을 완료하지 않고
인가 코드를 JSON으로 그대로 돌려준다(Swagger 등으로 POST /kakao를 수동
테스트할 때 씀). 그 외(기본값 "redirect")에는 콜백이 로그인을 끝내고
ACCESS_TOKEN_COOKIE_NAME/REFRESH_TOKEN_COOKIE_NAME 쿠키를 심어 프론트로
리다이렉트한다.
"""
ACCESS_TOKEN_COOKIE_NAME = "access_token"
REFRESH_TOKEN_COOKIE_NAME = "refresh_token"


def _kakao_login_url() -> str:
    """Swagger 설명에 넣을, 브라우저로 직접 열어야 하는 로그인 시작 URL.

    KAKAO_REDIRECT_URI의 origin(백엔드 주소)에 이 라우터의 prefix를 붙여 만든다.
    """
    settings = get_settings()
    origin = urlsplit(settings.KAKAO_REDIRECT_URI)
    return f"{origin.scheme}://{origin.netloc}{settings.API_PREFIX}/auth/kakao/login"


@router.get(
    "/kakao/login",
    summary="카카오 로그인 시작",
    description=(
        "code 파라미터만 받아 POST /kakao로 수동 테스트하려면 "
        f"`?mode=code`를 붙인다: [{_kakao_login_url()}?mode=code]"
        f"({_kakao_login_url()}?mode=code)"
    ),
)
async def kakao_login_start(mode: str = "redirect") -> RedirectResponse:
    """카카오 인가 페이지로 리다이렉트한다. 로그인 버튼은 이 엔드포인트로 이동하면 된다."""
    settings = get_settings()
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": settings.KAKAO_CLIENT_ID,
        "redirect_uri": settings.KAKAO_REDIRECT_URI,
        "response_type": "code",
        "state": state,
    }
    response = RedirectResponse(f"{settings.KAKAO_AUTHORIZE_URL}?{urlencode(params)}")
    response.set_cookie(
        STATE_COOKIE_NAME,
        f"{mode}:{state}",
        max_age=300,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get(
    "/kakao/callback",
    summary="카카오 로그인 콜백",
    description=(
        "카카오가 인가 코드를 돌려주는 콜백. 브라우저에서만 호출되며 Swagger로 "
        "직접 테스트하는 용도가 아니다. /login에서 고른 mode에 따라 동작이 다르다: "
        "redirect(기본)는 로그인을 완료해 토큰을 쿠키로 심고 프론트로 리다이렉트하고, "
        "code는 로그인 없이 인가 코드를 JSON으로 반환한다."
    ),
    include_in_schema=False,
)
async def kakao_login_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: AsyncSession = Depends(get_db),
):
    """카카오 인가 코드를 검증하고, mode에 따라 로그인 완료 또는 code 반환을 처리한다."""
    settings = get_settings()
    frontend_login_page = f"{settings.FRONTEND_URL}/login"

    def _to_login_with_error(reason: str) -> RedirectResponse:
        response = RedirectResponse(f"{frontend_login_page}?error={reason}")
        response.delete_cookie(STATE_COOKIE_NAME)
        return response

    if error is not None:
        return _to_login_with_error(error)
    if code is None:
        return _to_login_with_error("no_code")

    cookie_value = request.cookies.get(STATE_COOKIE_NAME) or ""
    mode, _, cookie_state = cookie_value.partition(":")
    if not cookie_state or cookie_state != state:
        return _to_login_with_error("invalid_state")

    if mode == "code":
        response = JSONResponse({"code": code})
        response.delete_cookie(STATE_COOKIE_NAME)
        return response

    try:
        tokens = await login_with_kakao(session, code)
    except KakaoAuthError:
        return _to_login_with_error("kakao_auth_failed")
    except InactiveAccountError:
        return _to_login_with_error("inactive_account")

    response = RedirectResponse(f"{settings.FRONTEND_URL}/company-profile")
    response.set_cookie(
        ACCESS_TOKEN_COOKIE_NAME,
        tokens["access_token"],
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        REFRESH_TOKEN_COOKIE_NAME,
        tokens["refresh_token"],
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(STATE_COOKIE_NAME)
    return response


@router.post(
    "/kakao",
    response_model=TokenResponse,
    summary="카카오 로그인",
    responses={
        401: {"description": "카카오 인증 실패"},
        403: {"description": "비활성화된 계정"},
    },
)
async def kakao_login(
    payload: KakaoLoginRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """카카오 인가 코드로 로그인하고 자체 JWT 토큰 쌍을 반환한다."""
    try:
        tokens = await login_with_kakao(session, payload.code)
    except KakaoAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    except InactiveAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return TokenResponse(**tokens)


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    summary="access token 재발급",
    responses={
        401: {"description": "refresh token이 유효하지 않음"},
        403: {"description": "비활성화된 계정"},
    },
)
async def refresh(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_db),
) -> AccessTokenResponse:
    """refresh token으로 새 access token을 발급받는다."""
    try:
        result = await refresh_access_token(session, payload.refresh_token)
    except RefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    except InactiveAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return AccessTokenResponse(**result)

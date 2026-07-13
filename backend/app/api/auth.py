"""인증 라우터.

HTTP 입출력과 예외 변환만 담당하고 비즈니스 로직은 서비스에 위임한다.
"""

import secrets
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    AccessTokenResponse,
    KakaoLoginRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)
from app.services import company_service
from app.services.auth_service import (
    InactiveAccountError,
    RefreshTokenError,
    login_with_kakao,
    refresh_access_token,
    withdraw_account,
)
from app.utils.auth_cookies import (
    REFRESH_TOKEN_COOKIE_NAME,
    clear_auth_cookies,
    set_access_cookie,
    set_refresh_cookie,
)
from app.utils.kakao_client import KakaoAuthError

router = APIRouter()

STATE_COOKIE_NAME = "kakao_oauth_state"
"""로그인 시작과 콜백 사이에서 CSRF 방지용 state·모드를 대조하기 위한 쿠키.

값은 "{mode}:{state}" 형태. mode가 "code"면 콜백이 로그인을 완료하지 않고
인가 코드를 JSON으로 그대로 돌려준다(Swagger 등으로 POST /kakao를 수동
테스트할 때 씀). 그 외(기본값 "redirect")에는 콜백이 로그인을 끝내고
access_token/refresh_token 쿠키를 심어 프론트로 리다이렉트한다.
"""


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

    # 기업 프로필을 이미 작성한 유저는 그 페이지를 건너뛰고 바로 업로드로
    # 보낸다. 미작성/신규 유저만 프로필 작성 페이지로 보낸다.
    profile = await company_service.get_my_profile(session, tokens["user_id"])
    next_path = (
        "/upload"
        if company_service.is_profile_complete(profile)
        else "/company-profile"
    )
    response = RedirectResponse(f"{settings.FRONTEND_URL}{next_path}")
    set_access_cookie(response, tokens["access_token"])
    set_refresh_cookie(response, tokens["refresh_token"])
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
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    session: AsyncSession = Depends(get_db),
) -> AccessTokenResponse:
    """refresh token으로 새 access token을 발급받는다.

    refresh token은 요청 바디(Swagger 등 수동 테스트)나 refresh_token 쿠키
    (브라우저 자동 전송) 어느 쪽으로든 받는다. 발급한 새 access token은
    응답 바디로 돌려주는 동시에 access_token 쿠키에도 다시 심어, 브라우저
    흐름에서 별도 처리 없이 곧바로 갱신되게 한다.
    """
    refresh_token = (payload.refresh_token if payload else None) or request.cookies.get(
        REFRESH_TOKEN_COOKIE_NAME
    )
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh token이 없습니다",
        )

    try:
        result = await refresh_access_token(session, refresh_token)
    except RefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    except InactiveAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc

    set_access_cookie(response, result["access_token"])
    return AccessTokenResponse(**result)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="로그아웃",
    description=(
        "access_token/refresh_token 쿠키를 삭제한다. httpOnly 쿠키는 JS로 지울 "
        "수 없어 서버가 Set-Cookie(Max-Age=0)로 만료시킨다. 인증 없이 호출할 수 "
        "있어(토큰 만료 상태여도) 항상 쿠키를 정리한다."
    ),
)
async def logout() -> Response:
    """인증 쿠키를 삭제한다."""
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(response)
    return response


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="회원탈퇴",
    description=(
        "카카오 연결 끊기(unlink) 후 탈퇴 처리한다: 기업 프로필/사업계획서/"
        "매칭 기록 등 딸린 데이터는 전부 삭제하고, 계정(user)은 status를 "
        "WITHDRAWN으로 바꾸고 개인정보(email/name/nickname)를 익명화한다. "
        "kakao_id는 남겨 같은 카카오 계정으로 다시 로그인하면 재가입 "
        "처리되지만(이전 데이터는 복구되지 않음), 인증 쿠키도 함께 삭제한다."
    ),
    responses={
        401: {"description": "인증되지 않음"},
        403: {"description": "비활성화된 계정"},
        502: {"description": "카카오 연결 끊기 실패 (탈퇴 미처리, 재시도 가능)"},
    },
)
async def withdraw(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """현재 로그인한 유저를 탈퇴 처리하고 인증 쿠키를 삭제한다."""
    try:
        await withdraw_account(session, current_user)
    except KakaoAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(response)
    return response


@router.get(
    "/me",
    response_model=UserResponse,
    summary="현재 로그인한 유저 정보",
    responses={
        401: {"description": "인증되지 않음"},
        403: {"description": "비활성화된 계정"},
    },
)
async def me(current_user: User = Depends(get_current_user)) -> User:
    """access token(쿠키 또는 Bearer)으로 인증된 유저 정보를 반환한다."""
    return current_user

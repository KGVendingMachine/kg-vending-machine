"""인증 라우터.

HTTP 입출력과 예외 변환만 담당하고 비즈니스 로직은 서비스에 위임한다.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.auth import (
    AccessTokenResponse,
    KakaoLoginRequest,
    RefreshRequest,
    TokenResponse,
)
from app.services.auth_service import (
    RefreshTokenError,
    login_with_kakao,
    refresh_access_token,
)
from app.utils.kakao_client import KakaoAuthError

router = APIRouter()


@router.post("/kakao", response_model=TokenResponse)
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
    return TokenResponse(**tokens)


@router.post("/refresh", response_model=AccessTokenResponse)
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
    return AccessTokenResponse(**result)

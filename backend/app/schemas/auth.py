"""인증 관련 요청/응답 스키마."""

from pydantic import BaseModel


class KakaoLoginRequest(BaseModel):
    """프론트가 카카오에서 받은 인가 코드를 전달한다."""

    code: str


class TokenResponse(BaseModel):
    """로그인 성공 시 발급하는 자체 JWT 토큰 쌍."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """access token 재발급을 위해 refresh token을 전달한다."""

    refresh_token: str


class AccessTokenResponse(BaseModel):
    """재발급된 access token."""

    access_token: str
    token_type: str = "bearer"

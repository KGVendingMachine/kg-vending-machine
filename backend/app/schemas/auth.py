"""인증 관련 요청/응답 스키마."""

from pydantic import BaseModel, ConfigDict, Field


class KakaoLoginRequest(BaseModel):
    """프론트가 카카오에서 받은 인가 코드를 전달한다."""

    code: str = Field(
        ...,
        examples=["aBcD1234EfGh5678IjKl"],
        description="카카오 로그인 후 리다이렉트로 받은 인가 코드",
    )


class DevLoginRequest(BaseModel):
    """개발 환경 전용: 카카오 로그인 없이 DB에 있는 user.id로 바로 토큰을 발급받는다."""

    user_id: int = Field(..., examples=[1], description="DB에 존재하는 user.id")


class TokenResponse(BaseModel):
    """로그인 성공 시 발급하는 자체 JWT 토큰 쌍."""

    access_token: str = Field(
        ...,
        examples=["eyJhbGciOiJIUzI1NiInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.abc123"],
    )
    refresh_token: str = Field(
        ...,
        examples=["eyJhbGciOiJIUzI1NiInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.xyz789"],
    )
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """access token 재발급을 위해 refresh token을 전달한다."""

    refresh_token: str = Field(
        ...,
        examples=["eyJhbGciOiJIUzI1NiInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.xyz789"],
        description="로그인 시 발급받은 refresh token",
    )


class AccessTokenResponse(BaseModel):
    """재발급된 access token."""

    access_token: str = Field(
        ...,
        examples=["eyJhbGciOiJIUzI1NiInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.new456"],
    )
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """현재 로그인한 유저 정보(GET /auth/me). 토큰·kakao_id 등 민감값은 제외한다."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str | None = None
    name: str | None = None
    nickname: str | None = None
    role: str
    status: str

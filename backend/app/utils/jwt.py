"""자체 발급 JWT의 생성/검증 유틸.

카카오 토큰이 아니라 우리 서비스가 로그인 이후 발급하는 토큰을 다룬다.
access token은 매 요청 인증에, refresh token은 access token 재발급에 쓴다.
"""

from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings

settings = get_settings()

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def _create_token(
    subject: str,
    expires_delta: timedelta,
    token_type: str,
    extra_claims: dict | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: str | int, role: str | None = None) -> str:
    """subject(보통 user.id)와 역할(role)을 담은 access token을 발급한다.

    role은 인가(권한) 판단에 쓰려고 클레임에 실어둔다. 매 요청마다 DB를
    다시 조회하지 않고 토큰만으로 역할을 알 수 있다(대신 역할이 바뀌면
    새 토큰을 받기 전까지는 이전 역할이 유지된다).
    """
    extra = {"role": role} if role is not None else None
    return _create_token(
        str(subject),
        timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        ACCESS_TOKEN_TYPE,
        extra,
    )


def create_refresh_token(subject: str | int) -> str:
    """subject(보통 user.id)를 담은 refresh token을 발급한다."""
    return _create_token(
        str(subject),
        timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        REFRESH_TOKEN_TYPE,
    )


def decode_token(token: str) -> dict:
    """토큰을 검증하고 payload를 반환한다.

    서명이 틀리거나 만료된 경우 jwt.InvalidTokenError(하위 예외 포함)를
    던진다. 호출하는 쪽(라우터)에서 잡아 401로 변환한다.
    """
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])

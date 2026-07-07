"""카카오 로그인 오케스트레이션.

인가 코드로 카카오 사용자를 확인하고, 우리 DB에 유저를 upsert한 뒤,
서비스 전용 JWT(access/refresh)를 발급한다. 카카오 토큰은 여기서만 쓰고
버린다.
"""

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.user_repository import get_by_id, upsert_on_login
from app.utils import kakao_client
from app.utils.jwt import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
)


class RefreshTokenError(Exception):
    """refresh token이 유효하지 않을 때. 라우터에서 401로 변환한다."""


def _extract_profile(user_info: dict) -> dict:
    """카카오 사용자 정보 응답에서 우리가 저장할 필드만 뽑아낸다.

    회원번호(id)는 항상 오지만, 이메일/이름/닉네임은 사용자가 제공에
    동의하지 않으면 없을 수 있어 None을 허용한다.
    """
    if "id" not in user_info:
        raise kakao_client.KakaoAuthError("카카오 응답에 회원번호(id)가 없습니다")

    account = user_info.get("kakao_account") or {}
    profile = account.get("profile") or {}
    return {
        "kakao_id": str(user_info["id"]),
        "email": account.get("email"),
        "name": account.get("name"),
        "nickname": profile.get("nickname"),
    }


async def login_with_kakao(session: AsyncSession, code: str) -> dict[str, str]:
    """인가 코드로 로그인을 처리하고 자체 JWT 토큰 쌍을 반환한다."""
    kakao_token = await kakao_client.exchange_code_for_token(code)
    user_info = await kakao_client.fetch_kakao_user(kakao_token)
    fields = _extract_profile(user_info)

    user = await upsert_on_login(session, **fields)
    await session.commit()

    return {
        "access_token": create_access_token(user.id, role=user.role),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
    }


async def refresh_access_token(
    session: AsyncSession, refresh_token: str
) -> dict[str, str]:
    """refresh token을 검증해 새 access token을 발급한다.

    검증(서명·만료), 토큰 종류(refresh), 유저 존재를 모두 통과해야 한다.
    유저의 현재 role을 다시 읽어 새 access token 클레임에 반영한다(로그인
    이후 role이 바뀌었으면 재발급 시점에 갱신됨). 유효하지 않으면
    RefreshTokenError를 던진다.
    """
    try:
        payload = decode_token(refresh_token)
    except jwt.InvalidTokenError as exc:
        raise RefreshTokenError("유효하지 않은 refresh token입니다") from exc

    if payload.get("type") != REFRESH_TOKEN_TYPE:
        raise RefreshTokenError("refresh token이 아닙니다")

    subject = payload.get("sub")
    if subject is None:
        raise RefreshTokenError("잘못된 토큰입니다")

    user = await get_by_id(session, int(subject))
    if user is None:
        raise RefreshTokenError("사용자를 찾을 수 없습니다")

    return {
        "access_token": create_access_token(user.id, role=user.role),
        "token_type": "bearer",
    }

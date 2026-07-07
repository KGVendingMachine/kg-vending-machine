"""카카오 로그인 오케스트레이션.

인가 코드로 카카오 사용자를 확인하고, 우리 DB에 유저를 upsert한 뒤,
서비스 전용 JWT(access/refresh)를 발급한다. 카카오 토큰은 여기서만 쓰고
버린다.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.user_repository import upsert_on_login
from app.utils import kakao_client
from app.utils.jwt import create_access_token, create_refresh_token


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
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
    }

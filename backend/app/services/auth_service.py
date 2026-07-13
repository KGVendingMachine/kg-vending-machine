"""카카오 로그인 오케스트레이션.

인가 코드로 카카오 사용자를 확인하고, 우리 DB에 유저를 upsert한 뒤,
서비스 전용 JWT(access/refresh)를 발급한다. 카카오 토큰은 여기서만 쓰고
버린다.
"""

import logging

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.user_repository import (
    delete_owned_data,
    get_by_id,
    reactivate,
    upsert_on_login,
    withdraw,
)
from app.utils import kakao_client
from app.utils.file_storage import delete_stored_file
from app.utils.jwt import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
)

logger = logging.getLogger(__name__)


class RefreshTokenError(Exception):
    """refresh token이 유효하지 않을 때. 라우터에서 401로 변환한다."""


class InactiveAccountError(Exception):
    """비활성 계정. 라우터에서 403으로 변환한다.

    로그인은 차단(BLOCKED)만 거부하고 탈퇴(WITHDRAWN)는 재가입 처리한다.
    로그인 이후(access/refresh 검증)는 ACTIVE가 아니면 모두 거부한다.
    """


class UserNotFoundError(Exception):
    """dev-login에서 존재하지 않는 user_id를 요청했을 때. 라우터에서 404로 변환한다."""


ACTIVE_STATUS = "ACTIVE"
WITHDRAWN_STATUS = "WITHDRAWN"
BLOCKED_STATUS = "BLOCKED"


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


async def login_with_kakao(session: AsyncSession, code: str) -> dict[str, str | int]:
    """인가 코드로 로그인을 처리하고 자체 JWT 토큰 쌍을 반환한다.

    user_id도 함께 돌려준다 - 로그인 콜백이 로그인 직후 리다이렉트 대상을
    결정하려면(예: 기업 프로필 작성 여부) 토큰 발급과 별개로 유저를 알아야
    한다. TokenResponse에는 없는 필드라 extra로 무시된다.
    """
    kakao_token = await kakao_client.exchange_code_for_token(code)
    user_info = await kakao_client.fetch_kakao_user(kakao_token)
    fields = _extract_profile(user_info)

    user = await upsert_on_login(session, **fields)
    # 차단 계정은 로그인 자체를 거부한다. commit 전에 막아 프로필/
    # last_login 갱신도 롤백되게 한다.
    if user.status == BLOCKED_STATUS:
        raise InactiveAccountError("비활성화된 계정입니다")
    # 탈퇴 계정이 같은 카카오 계정으로 다시 로그인하면 재가입으로 본다.
    # 익명화로 지웠던 프로필은 위 upsert가 카카오 값으로 이미 다시 채웠다.
    if user.status == WITHDRAWN_STATUS:
        await reactivate(session, user)
    await session.commit()

    return {
        "access_token": create_access_token(user.id, role=user.role),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
        "user_id": user.id,
    }


async def dev_login(session: AsyncSession, user_id: int) -> dict[str, str | int]:
    """개발 환경 전용: 카카오 로그인 없이 기존 user_id로 바로 토큰 쌍을 발급한다.

    DB에 이미 있는 유저만 대상으로 한다(신규 생성 없음) - 각 개발자가 카카오
    로그인으로 한 번 만들어둔 계정을 role/status 그대로 재사용해 API를
    테스트하려는 용도라, status 검사는 하지 않는다(예: WITHDRAWN 계정으로
    로그인해 이후 요청이 403 나는지 확인하는 것도 이 엔드포인트의 용도).
    """
    user = await get_by_id(session, user_id)
    if user is None:
        raise UserNotFoundError(f"user_id={user_id}에 해당하는 유저가 없습니다")

    return {
        "access_token": create_access_token(user.id, role=user.role),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
        "user_id": user.id,
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
    if user.status != ACTIVE_STATUS:
        raise InactiveAccountError("비활성화된 계정입니다")

    return {
        "access_token": create_access_token(user.id, role=user.role),
        "token_type": "bearer",
    }


async def withdraw_account(session: AsyncSession, user: User) -> None:
    """회원 탈퇴를 처리한다: 카카오 연결 끊기 + 딸린 데이터 삭제 + 계정 익명화.

    카카오 unlink를 먼저 호출한다 — 실패하면 KakaoAuthError가 올라가
    DB 변경 없이 탈퇴가 중단되고, 사용자가 다시 시도할 수 있다.
    (반대 순서면 탈퇴 커밋 후 unlink 실패 시 재시도 경로가 없다 —
    탈퇴 유저는 인증이 막혀 이 엔드포인트를 다시 못 부른다.)

    company_profile/business_plan/match_log 등 유저에 딸린 데이터는
    전부 하드 삭제한다(재가입해도 이전 데이터가 남지 않게). user 행
    자체는 kakao_id를 남겨 재로그인 매칭에 써야 해서 소프트 삭제
    (WITHDRAWN + 개인정보 익명화)로 유지한다.

    저장 파일 삭제는 DB 트랜잭션 밖의 IO라 커밋이 끝난 뒤에 한다 —
    파일부터 지우고 커밋이 실패하면 DB에는 참조가 남았는데 파일만
    없는 상태가 되어 더 나쁘다. 커밋 후 지우면 실패해도 고아 파일만
    남고(수동 정리 가능) 탈퇴 자체는 이미 끝나 있다.

    이미 발급된 JWT는 deps.get_current_user/refresh가 매 요청 status를
    확인하므로 커밋 즉시 무력화된다(403).
    """
    await kakao_client.unlink_user(user.kakao_id)
    file_paths = await delete_owned_data(session, user.id)
    await withdraw(session, user)
    await session.commit()

    for path in file_paths:
        try:
            delete_stored_file(path)
        except OSError:
            logger.warning("탈퇴 후 파일 삭제 실패: %s", path, exc_info=True)

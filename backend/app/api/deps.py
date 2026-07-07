"""라우터 공용 의존성.

요청의 JWT를 검증해 "이 요청이 누구인가"를 판별한다. 보호가 필요한
엔드포인트에 아래처럼 Depends로 붙여 쓴다(파라미터로 받으면 FastAPI가
요청마다 토큰을 검증해 User를 주입해 준다).

    from fastapi import Depends
    from app.api.deps import get_current_user, require_admin
    from app.models.user import User

    # 로그인한 유저만 접근 (토큰 없거나 틀리면 자동 401)
    @router.get("/bookmarks")
    async def my_bookmarks(user: User = Depends(get_current_user)):
        ...  # user.id로 본인 데이터 조회

    # 관리자만 접근 (USER면 403)
    @router.get("/admin/stats")
    async def admin_stats(user: User = Depends(require_admin)):
        ...
"""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.repositories.user_repository import get_by_id
from app.utils.jwt import ACCESS_TOKEN_TYPE, decode_token

# Authorization: Bearer <token> 헤더에서 토큰을 뽑는다(Swagger Authorize 연동).
bearer_scheme = HTTPBearer()

ADMIN_ROLE = "ADMIN"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    """access token을 검증하고 해당 유저를 반환한다.

    토큰이 없거나(문지기 단계) 서명·만료가 잘못됐거나, refresh 토큰을
    잘못 보냈거나, 유저가 존재하지 않으면 401.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="유효하지 않은 인증 정보입니다",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(credentials.credentials)
    except jwt.InvalidTokenError as exc:
        raise credentials_exception from exc

    # refresh 토큰으로는 API 접근을 막는다(access 전용).
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise credentials_exception

    subject = payload.get("sub")
    if subject is None:
        raise credentials_exception

    user = await get_by_id(session, int(subject))
    if user is None:
        raise credentials_exception
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """관리자(role=ADMIN)만 통과시킨다. 아니면 403."""
    if user.role != ADMIN_ROLE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다",
        )
    return user

"""user 테이블 접근 계층.

SQLAlchemy 세션을 직접 다루는 유일한 계층. 커밋은 하지 않고,
호출하는 서비스가 트랜잭션 경계를 관리한다(notice 수집과 동일한 규칙).
"""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    """PK(id)로 유저를 조회한다. 없으면 None."""
    return await session.get(User, user_id)


async def get_by_kakao_id(session: AsyncSession, kakao_id: str) -> User | None:
    """카카오 회원번호로 유저를 조회한다. 없으면 None."""
    result = await session.execute(select(User).where(User.kakao_id == kakao_id))
    return result.scalar_one_or_none()


async def upsert_on_login(
    session: AsyncSession,
    *,
    kakao_id: str,
    email: str | None,
    name: str | None,
    nickname: str | None,
) -> User:
    """로그인 시 유저를 upsert하고 최종 로그인 시각을 갱신해 User를 반환한다.

    uq_user_kakao_id 유니크 제약을 이용한 INSERT ... ON CONFLICT로 처리해
    동시 로그인 요청이 겹쳐도 같은 kakao_id로 유저가 중복 생성되지 않는다.

    프로필(email/name/nickname)은 카카오 값으로 갱신하되, 사용자가 제공에
    동의하지 않아 값이 없을 때(None) 기존 값을 덮어써 지우지 않도록
    COALESCE(신규, 기존)를 쓴다.
    """
    insert_stmt = pg_insert(User).values(
        kakao_id=kakao_id,
        email=email,
        name=name,
        nickname=nickname,
        last_login_at=func.now(),
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[User.kakao_id],
        set_={
            "email": func.coalesce(insert_stmt.excluded.email, User.email),
            "name": func.coalesce(insert_stmt.excluded.name, User.name),
            "nickname": func.coalesce(insert_stmt.excluded.nickname, User.nickname),
            "last_login_at": func.now(),
            "updated_at": func.now(),
        },
    ).returning(User.id)
    result = await session.execute(stmt)
    user_id = result.scalar_one()
    return await session.get_one(User, user_id)

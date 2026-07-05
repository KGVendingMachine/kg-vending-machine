"""
tests/conftest.py

DB 접근이 필요한 테스트를 위한 공통 fixture.
각 테스트는 하나의 커넥션 위에서 외부 트랜잭션을 열어두고, 그 안에서
Session이 SAVEPOINT 단위로 commit/rollback을 하도록 구성한다 (join_transaction_mode=
"create_savepoint"). 테스트가 끝나면 외부 트랜잭션을 롤백하므로 리포지토리 함수가
내부적으로 session.commit()을 호출해도 실제 DB에는 아무 것도 남지 않는다.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.models  # noqa: F401  모든 모델을 등록해서 FK 대상 테이블을 metadata에 올려둠
from app.core.config import get_settings
from app.models.company import CompanyProfile
from app.models.user import User


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db_session():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)

    async with engine.connect() as conn:
        await conn.begin()

        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()

    await engine.dispose()


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """business_plan -> company_profile -> user FK를 만족시키기 위한 최소 유저."""
    user = User(kakao_id="test-kakao-id")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def test_company_profile(
    db_session: AsyncSession, test_user: User
) -> CompanyProfile:
    profile = CompanyProfile(user_id=test_user.id)
    db_session.add(profile)
    await db_session.flush()
    return profile

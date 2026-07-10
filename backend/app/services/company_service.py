"""기업 프로필 서비스.

본인 프로필의 조회/저장을 오케스트레이션한다. 트랜잭션 경계(commit)는
여기서 관리한다.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import CompanyProfile
from app.repositories import company_repository


async def get_my_profile(session: AsyncSession, user_id: int) -> CompanyProfile | None:
    """본인의 대표 기업 프로필을 반환한다. 없으면 None."""
    return await company_repository.get_primary_by_user(session, user_id)


async def save_my_profile(
    session: AsyncSession, user_id: int, fields: dict
) -> CompanyProfile:
    """본인의 대표 기업 프로필을 부분 갱신/생성하고 커밋한다."""
    profile = await company_repository.upsert_primary(session, user_id, fields)
    await session.commit()
    # async_session_factory는 expire_on_commit=False라 commit 후에도 속성이
    # 살아 있다(id는 flush 시 RETURNING으로 채워짐). 별도 refresh 불필요.
    return profile

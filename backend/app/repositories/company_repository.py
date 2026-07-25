"""company_profile 테이블 접근 계층.

커밋은 하지 않고 호출하는 서비스가 트랜잭션 경계를 관리한다(user_repository와
동일 규칙). 한 유저의 대표 프로필(is_primary=True) 한 행만 다룬다.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import CompanyProfile


async def get_primary_by_user(
    session: AsyncSession, user_id: int
) -> CompanyProfile | None:
    """유저의 대표 기업 프로필을 반환한다. 없으면 None."""
    result = await session.execute(
        select(CompanyProfile)
        .where(
            CompanyProfile.user_id == user_id,
            CompanyProfile.is_primary.is_(True),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def upsert_primary(
    session: AsyncSession, user_id: int, fields: dict
) -> CompanyProfile:
    """유저의 대표 프로필을 부분 갱신하거나, 없으면 생성한다.

    fields에 담긴 컬럼만 덮어쓴다(부분 갱신). 나머지 컬럼은 그대로 유지되어
    나중에 다른 필드를 보내면 같은 행에 누적된다.
    """
    profile = await get_primary_by_user(session, user_id)
    if profile is None:
        profile = CompanyProfile(user_id=user_id, is_primary=True, **fields)
        session.add(profile)
    else:
        for key, value in fields.items():
            setattr(profile, key, value)
    await session.flush()
    return profile


async def get_by_id(
    session: AsyncSession, company_profile_id: int
) -> CompanyProfile | None:
    """프로필을 id로 반환한다. 없으면 None."""
    return await session.get(CompanyProfile, company_profile_id)

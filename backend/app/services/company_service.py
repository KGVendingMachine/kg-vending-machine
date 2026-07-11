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


def is_profile_complete(profile: CompanyProfile | None) -> bool:
    """프로필 작성이 실질적으로 끝났다고 볼 수 있는지 판단한다.

    upsert_primary는 빈 필드로도 row를 만들 수 있어 "row가 존재한다"만으로는
    작성 완료를 보장하지 못한다. 대표자명/사업자등록번호 중 하나라도 채워져
    있으면 실제로 입력을 진행한 것으로 본다.
    """
    if profile is None:
        return False
    return bool(profile.representative_name or profile.business_registration_number)


async def save_my_profile(
    session: AsyncSession, user_id: int, fields: dict
) -> CompanyProfile:
    """본인의 대표 기업 프로필을 부분 갱신/생성하고 커밋한다."""
    profile = await company_repository.upsert_primary(session, user_id, fields)
    await session.commit()
    # async_session_factory는 expire_on_commit=False라 commit 후에도 속성이
    # 살아 있다(id는 flush 시 RETURNING으로 채워짐). 별도 refresh 불필요.
    return profile

"""기업 프로필 서비스.

본인 프로필의 조회/저장을 오케스트레이션한다. 트랜잭션 경계(commit)는
여기서 관리한다. 요청 스키마의 입력 형식(설립연도, 시/도 이름)을 DB 컬럼
형식(founded_date, region_code)으로 바꾸는 변환도 여기서 담당한다.
"""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import CompanyProfile
from app.repositories import company_repository
from app.schemas.company import REGION_CODES


def _convert_to_column_fields(fields: dict) -> dict:
    """요청 필드를 company_profile 컬럼 형식으로 변환한다.

    - founded_year(연도) → founded_date(해당 연도 1월 1일). 사업계획서에서도
      설립연도만 추출되는 경우가 많아 월/일은 1월 1일로 통일한다.
    - region_name(시/도 이름) → region_code(행정표준코드)를 함께 채운다.
      스키마 검증을 통과한 이름만 들어오므로 매핑 실패는 없다.
    """
    converted = dict(fields)
    if "founded_year" in converted:
        year = converted.pop("founded_year")
        converted["founded_date"] = date(year, 1, 1) if year is not None else None
    if "region_name" in converted:
        name = converted["region_name"]
        converted["region_code"] = REGION_CODES.get(name) if name else None
    return converted


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
    profile = await company_repository.upsert_primary(
        session, user_id, _convert_to_column_fields(fields)
    )
    await session.commit()
    # async_session_factory는 expire_on_commit=False라 commit 후에도 속성이
    # 살아 있다(id는 flush 시 RETURNING으로 채워짐). 별도 refresh 불필요.
    return profile

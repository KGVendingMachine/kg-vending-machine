"""기업 프로필 서비스.

본인 프로필의 조회/저장을 오케스트레이션한다. 트랜잭션 경계(commit)는
여기서 관리한다. 요청 스키마의 입력 형식(설립연도, 시/도 이름)을 DB 컬럼
형식(founded_date, region_code)으로 바꾸는 변환도 여기서 담당한다.
"""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import CompanyProfile
from app.repositories import company_repository
from app.schemas.company import PRE_FOUNDER_STAGE, PRE_FOUNDER_TYPE, REGION_CODES
from app.services.company_size import derive_company_size


class CompanyProfileInconsistentError(Exception):
    """business_type과 company_stage의 조합이 모순될 때 발생.

    예: business_type=예비창업자인데 company_stage=중소기업(또는 그 반대).
    스키마의 model_validator는 한 요청 안에 두 필드가 함께 온 경우만 잡을 수
    있어서, 부분 갱신으로 한 필드만 보내 기존 저장값과 모순되는 경우는 여기서
    기존 프로필과 병합한 뒤 검증한다.
    """


def _validate_stage_consistency(
    effective_business_type: str | None, effective_company_stage: str | None
) -> None:
    if effective_business_type is None or effective_company_stage is None:
        return
    is_pre_founder = effective_business_type == PRE_FOUNDER_TYPE
    is_pre_founder_stage = effective_company_stage == PRE_FOUNDER_STAGE
    if is_pre_founder != is_pre_founder_stage:
        raise CompanyProfileInconsistentError(
            "사업자유형과 기업 단계 조합이 올바르지 않습니다"
            "(예비창업자는 기업 단계가 예비창업자여야 하고, 그 외에는 예비창업자일 수 없습니다)"
        )


# 사업자등록 이후에만 의미가 있는 필드. 예비창업자로 전환되면 null로 정리한다.
# company_size는 여기 없다 — 입력이 아니라 파생값이라, annual_revenue가 null로
# 정리되면 _derive_and_set_company_size가 알아서 None으로 만든다.
_PRE_FOUNDER_ONLY_FIELDS = (
    "business_registration_number",
    "founded_year",
    "employee_count",
    "annual_revenue",
)


def _apply_pre_founder_transition(fields: dict) -> dict:
    """이번 요청이 business_type을 예비창업자로 바꾸는 경우 관련 필드를 정리한다.

    예비창업자는 사업자등록 전이므로 등록번호·설립연도·기업규모·근로자수·매출은
    존재할 수 없다. company_stage도 예비창업자로 강제한다 — 요청에 다른 값이
    함께 왔더라도(프론트를 거치지 않은 직접 API 호출 포함) 이 값들로 덮어써서
    모순된 조합이 저장되지 않게 한다.
    """
    if fields.get("business_type") != PRE_FOUNDER_TYPE:
        return fields
    cleaned = dict(fields)
    cleaned["company_stage"] = PRE_FOUNDER_STAGE
    for key in _PRE_FOUNDER_ONLY_FIELDS:
        cleaned[key] = None
    return cleaned


def _derive_and_set_company_size(fields: dict, existing: CompanyProfile | None) -> dict:
    """이번 요청 반영 후의 업종·매출로 company_size를 산출해 채운다.

    company_size는 사용자가 고르는 값이 아니라 파생값이라, 저장할 때마다
    최종 상태(이번 요청 + 기존 저장값)를 기준으로 다시 계산한다. 부분
    갱신이라 이번 요청에 industry_code/annual_revenue가 없으면 기존 값을
    그대로 쓴다.
    """
    industry_code = fields.get(
        "industry_code", existing.industry_code if existing else None
    )
    annual_revenue = fields.get(
        "annual_revenue", existing.annual_revenue if existing else None
    )
    result = dict(fields)
    result["company_size"] = derive_company_size(industry_code, annual_revenue)
    return result


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
    """본인의 대표 기업 프로필을 부분 갱신/생성하고 커밋한다.

    business_type이 예비창업자로 바뀌는 요청이면 사업자등록 이후에만 의미
    있는 필드를 null로 정리하고 company_stage를 예비창업자로 맞춘다. 그 외
    business_type/company_stage 중 하나만 이번 요청에 왔다면 기존 저장값과
    합쳐서 정합성을 검증한다(둘 다 부분 갱신 대상이라 요청 본문만으로는
    모순 여부를 판단할 수 없다).
    """
    fields = _apply_pre_founder_transition(fields)

    existing = await company_repository.get_primary_by_user(session, user_id)
    effective_business_type = fields.get(
        "business_type", existing.business_type if existing else None
    )
    effective_company_stage = fields.get(
        "company_stage", existing.company_stage if existing else None
    )
    _validate_stage_consistency(effective_business_type, effective_company_stage)

    fields = _derive_and_set_company_size(fields, existing)

    profile = await company_repository.upsert_primary(
        session, user_id, _convert_to_column_fields(fields)
    )
    await session.commit()
    # async_session_factory는 expire_on_commit=False라 commit 후에도 속성이
    # 살아 있다(id는 flush 시 RETURNING으로 채워짐). 별도 refresh 불필요.
    return profile

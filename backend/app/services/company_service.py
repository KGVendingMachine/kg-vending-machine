"""기업 프로필 서비스.

본인 프로필의 조회/저장을 오케스트레이션한다. 트랜잭션 경계(commit)는
여기서 관리한다. 요청 스키마의 입력 형식(설립연도, 시/도 이름)을 DB 컬럼
형식(founded_date, region_code)으로 바꾸는 변환도 여기서 담당한다.
"""

from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import CompanyProfile
from app.repositories import company_repository
from app.schemas.business_plan import NormalizedBusinessPlanSchema
from app.schemas.company import BUSINESS_TYPES, PRE_FOUNDER_TYPE, REGION_CODES
from app.services.company_size import derive_company_size


class CompanyProfileInconsistentError(Exception):
    """business_type=예비창업자인데 company_stage가 채워져 있을 때 발생.

    예비창업자는 사업자등록 전이라 기업 단계(초기창업/중소기업) 자체가 적용
    되지 않는다. 스키마의 model_validator는 한 요청 안에 두 필드가 함께 온
    경우만 잡을 수 있어서, 부분 갱신으로 한 필드만 보내 기존 저장값과
    모순되는 경우는 여기서 기존 프로필과 병합한 뒤 검증한다.
    """


def _validate_stage_consistency(
    effective_business_type: str | None, effective_company_stage: str | None
) -> None:
    if effective_business_type != PRE_FOUNDER_TYPE or effective_company_stage is None:
        return
    raise CompanyProfileInconsistentError(
        "예비창업자는 기업 단계(초기창업/중소기업)를 함께 설정할 수 없습니다"
    )


# 사업자등록 이후에만 의미가 있는 필드. 예비창업자로 전환되면 null로 정리한다.
# company_size는 여기 없다 — 입력이 아니라 파생값이라, annual_revenue가 null로
# 정리되면 _derive_and_set_company_size가 알아서 None으로 만든다.
_PRE_FOUNDER_ONLY_FIELDS = (
    "business_registration_number",
    "founded_year",
    "employee_count",
    "annual_revenue",
    "company_stage",
)


def _apply_pre_founder_transition(fields: dict) -> dict:
    """이번 요청이 business_type을 예비창업자로 바꾸는 경우 관련 필드를 정리한다.

    예비창업자는 사업자등록 전이므로 등록번호·설립연도·근로자수·매출·기업
    단계는 존재할 수 없다. 요청에 다른 값이 함께 왔더라도(프론트를 거치지
    않은 직접 API 호출 포함) null로 덮어써서 모순된 조합이 저장되지 않게 한다.
    """
    if fields.get("business_type") != PRE_FOUNDER_TYPE:
        return fields
    cleaned = dict(fields)
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


async def save_my_profile(
    session: AsyncSession, user_id: int, fields: dict
) -> CompanyProfile:
    """본인의 대표 기업 프로필을 부분 갱신/생성하고 커밋한다.

    business_type이 예비창업자로 바뀌는 요청이면 사업자등록 이후에만 의미
    있는 필드(company_stage 포함)를 null로 정리한다. 그 외 business_type/
    company_stage 중 하나만 이번 요청에 왔다면 기존 저장값과 합쳐서
    정합성을 검증한다(둘 다 부분 갱신 대상이라 요청 본문만으로는 모순
    여부를 판단할 수 없다).
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


class MatchingConfirmationIncompleteError(Exception):
    """지역·기업형태가 비어 있어 매칭 확인을 기록할 수 없을 때.

    확인 모달의 "맞아요"는 두 값이 채워져 있어야 의미가 있다. 비어 있으면
    프론트가 버튼을 비활성화하지만, 직접 API 호출까지 막지는 못하므로 여기서
    다시 검증한다.
    """


async def confirm_matching_profile(
    session: AsyncSession, user_id: int
) -> CompanyProfile:
    """매칭 전 확인 모달의 "맞아요"를 기록하고 커밋한다.

    matching_confirmed_at이 채워지면 이후 매칭 시작 시 확인 모달을 건너뛴다.
    1차 필터링의 주요 축인 지역·기업형태가 비어 있으면 확인 자체가 성립하지
    않으므로 거부한다.
    """
    profile = await company_repository.get_primary_by_user(session, user_id)
    if profile is None or not profile.region_name or not profile.business_type:
        raise MatchingConfirmationIncompleteError(
            "지역과 사업자유형을 먼저 입력해야 매칭 정보를 확인할 수 있습니다"
        )
    profile.matching_confirmed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await session.commit()
    return profile


# ---------------------------------------------------------------------------
# 사업계획서 정규화 결과 → 프로필 자동 채움 (업로드 우선 온보딩, #142)
# ---------------------------------------------------------------------------

# 정규화가 "충청북도"처럼 전체 도(道) 명칭을 낼 때의 별칭. 약칭이 전체 명칭의
# 접두사인 경우("서울특별시"·"경기도"·"전북특별자치도" 등)는 아래
# _canonical_region_name의 접두사 매칭으로 잡히므로 여기 두지 않는다.
_REGION_FULL_NAME_ALIASES = {
    "충청북도": "충북",
    "충청남도": "충남",
    "전라남도": "전남",
    "전라북도": "전북",
    "경상북도": "경북",
    "경상남도": "경남",
}

# 자동 채움 대상 문자열 컬럼의 길이 제한(models/company.py). 넘는 값은 추출
# 오류일 가능성이 커서 잘라 넣지 않고 채움을 포기한다.
_AUTOFILL_MAX_LENGTHS = {"company_name": 255, "representative_name": 100}


def _canonical_region_name(raw: str | None) -> str | None:
    """정규화 결과의 지역 표기를 REGION_CODES 키(시/도 약칭)로 정리한다.

    "서울특별시 강남구" → "서울"처럼 접두사로 판정한다. 어느 시/도로도 정리하지
    못하면 None — 틀린 지역을 채우는 것보다 비워 두고 매칭 전 확인 모달에서
    직접 입력을 유도하는 편이 낫다.
    """
    if not raw:
        return None
    text = raw.strip()
    for full_name, short_name in _REGION_FULL_NAME_ALIASES.items():
        if text.startswith(full_name):
            return short_name
    for short_name in REGION_CODES:
        if text.startswith(short_name):
            return short_name
    return None


def _autofill_fields(
    normalized: NormalizedBusinessPlanSchema, profile: CompanyProfile
) -> dict:
    """프로필의 빈 컬럼에 한해 정규화 결과에서 채울 컬럼 값을 고른다.

    LLM 출력은 스키마 설명을 어길 수 있으므로 저장 전에 여기서 다시 검증한다
    (지역 표기 정리, business_type enum, 설립연도 범위, 문자열 길이).
    """
    company = normalized.company
    fields: dict = {}

    if not profile.company_name and company.name:
        fields["company_name"] = company.name.strip()
    if not profile.representative_name and company.ceo_name:
        fields["representative_name"] = company.ceo_name.strip()
    if profile.founded_date is None and company.founded_year is not None:
        if 1900 <= company.founded_year <= date.today().year:
            fields["founded_date"] = date(company.founded_year, 1, 1)
    if not profile.region_name:
        region = _canonical_region_name(company.region_name)
        if region is not None:
            fields["region_name"] = region
            fields["region_code"] = REGION_CODES[region]
    if not profile.business_type and company.business_type in BUSINESS_TYPES:
        fields["business_type"] = company.business_type

    for key, max_length in _AUTOFILL_MAX_LENGTHS.items():
        if key in fields and len(fields[key]) > max_length:
            del fields[key]

    # 예비창업자는 설립연도·사업자등록번호·기업 단계 등과 공존할 수 없다. 기존
    # 저장값이나 이번 추출값에 그런 필드가 있으면 설립 이력이 더 구체적인
    # 근거이므로 business_type 추출이 틀렸다고 보고 예비창업자 채움을 포기한다.
    # save_my_profile의 전환 규칙과 달리 여기서는 기존 값을 절대 지우지 않는다.
    if fields.get("business_type") == PRE_FOUNDER_TYPE and (
        "founded_date" in fields
        or profile.founded_date is not None
        or profile.business_registration_number
        or profile.company_stage
        or profile.employee_count is not None
        or profile.annual_revenue is not None
    ):
        del fields["business_type"]

    return fields


async def autofill_profile_from_business_plan(
    session: AsyncSession,
    company_profile_id: int,
    normalized: NormalizedBusinessPlanSchema,
) -> list[str]:
    """정규화 결과로 프로필의 빈 컬럼만 채우고 커밋한다. 채운 컬럼명을 반환.

    업로드 우선 온보딩: 프로필 입력 없이 업로드부터 한 유저의 프로필을
    사업계획서에서 뽑은 값으로 보완한다. 유저가 이미 입력한 컬럼은 정규화
    결과가 달라도 덮어쓰지 않는다 — 재업로드해도 기존 값은 그대로다.
    """
    profile = await company_repository.get_by_id(session, company_profile_id)
    if profile is None:
        return []

    fields = _autofill_fields(normalized, profile)
    if not fields:
        return []

    for key, value in fields.items():
        setattr(profile, key, value)
    await session.commit()
    return list(fields)

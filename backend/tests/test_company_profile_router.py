"""tests/test_company_profile_router.py

본인 기업 프로필 저장/조회(부분 갱신) 검증. 다른 라우터 테스트와 동일하게
라우터 함수를 직접 호출하고, db_session 픽스처로 트랜잭션을 격리한다.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from app.api.company_profile import (
    get_my_company_profile,
    save_my_company_profile,
)
from app.models.user import User
from app.schemas.company import CompanyProfileUpdate

pytestmark = pytest.mark.anyio


async def _make_user(db_session, kakao_id="company-test-kakao") -> User:
    user = User(kakao_id=kakao_id, status="ACTIVE", role="USER")
    db_session.add(user)
    await db_session.flush()
    return user


async def test_get_returns_none_before_save(db_session):
    user = await _make_user(db_session)
    result = await get_my_company_profile(current_user=user, session=db_session)
    assert result is None


async def test_save_then_get_round_trip(db_session):
    user = await _make_user(db_session)
    payload = CompanyProfileUpdate(
        representative_name="홍길동",
        business_registration_number="000-00-00000",
        company_size="소기업",
        employee_count=15,
    )

    saved = await save_my_company_profile(
        payload=payload, current_user=user, session=db_session
    )
    assert saved.representative_name == "홍길동"
    assert saved.employee_count == 15
    assert saved.user_id == user.id
    assert saved.is_primary is True

    fetched = await get_my_company_profile(current_user=user, session=db_session)
    assert fetched is not None
    assert fetched.id == saved.id
    assert fetched.company_size == "소기업"


async def test_partial_update_accumulates(db_session):
    """뒤에 다른 필드만 보내도 앞서 저장한 값은 유지되고 같은 행에 누적된다."""
    user = await _make_user(db_session)

    first = await save_my_company_profile(
        payload=CompanyProfileUpdate(representative_name="김대표"),
        current_user=user,
        session=db_session,
    )
    second = await save_my_company_profile(
        payload=CompanyProfileUpdate(employee_count=7),
        current_user=user,
        session=db_session,
    )

    assert second.id == first.id  # 새 행이 아니라 같은 행 갱신
    assert second.representative_name == "김대표"  # 이전 값 유지
    assert second.employee_count == 7


async def test_blank_strings_are_ignored(db_session):
    """폼 select 기본값 등 빈 문자열은 미입력으로 처리돼 exclude_unset에서 제외."""
    user = await _make_user(db_session)
    payload = CompanyProfileUpdate(
        representative_name="박대표",
        company_size="",  # 빈 값 → None 처리
    )
    fields = payload.model_dump(exclude_unset=True)
    # company_size는 값이 None이라 저장 대상엔 남지만 컬럼은 None으로 세팅된다.
    assert fields["representative_name"] == "박대표"
    assert fields["company_size"] is None

    saved = await save_my_company_profile(
        payload=payload, current_user=user, session=db_session
    )
    assert saved.representative_name == "박대표"
    assert saved.company_size is None


async def test_save_matching_fields_with_conversion(db_session):
    """매칭용 필드 저장: 설립연도→founded_date, 시/도 이름→region_code 변환 확인."""
    user = await _make_user(db_session, kakao_id="company-matching-fields")
    payload = CompanyProfileUpdate(
        business_type="법인사업자",
        company_stage="초기창업",
        industry_code="J",
        region_name="경북",
        founded_year=2021,
        annual_revenue=1_200_000_000,
    )

    saved = await save_my_company_profile(
        payload=payload, current_user=user, session=db_session
    )
    assert saved.business_type == "법인사업자"
    assert saved.company_stage == "초기창업"
    assert saved.industry_code == "J"
    assert saved.region_name == "경북"
    assert saved.region_code == "47"  # 행정표준코드 시도 2자리
    assert saved.founded_date == date(2021, 1, 1)
    assert saved.annual_revenue == 1_200_000_000


async def test_blank_matching_fields_clear_columns(db_session):
    """빈 문자열로 보낸 select 필드는 None으로 저장되고 파생 컬럼도 함께 비워진다."""
    user = await _make_user(db_session, kakao_id="company-blank-matching")
    await save_my_company_profile(
        payload=CompanyProfileUpdate(region_name="서울", business_type="개인사업자"),
        current_user=user,
        session=db_session,
    )

    saved = await save_my_company_profile(
        payload=CompanyProfileUpdate(region_name="", business_type=""),
        current_user=user,
        session=db_session,
    )
    assert saved.business_type is None
    assert saved.region_name is None
    assert saved.region_code is None  # region_name이 비면 코드도 함께 비운다


def test_update_rejects_unknown_enum_values():
    """정해진 집합 밖의 값은 스키마 검증에서 거부된다."""
    with pytest.raises(ValidationError):
        CompanyProfileUpdate(business_type="프리랜서")
    with pytest.raises(ValidationError):
        CompanyProfileUpdate(company_stage="상장")
    with pytest.raises(ValidationError):
        CompanyProfileUpdate(industry_code="Z")
    with pytest.raises(ValidationError):
        CompanyProfileUpdate(region_name="독도")


def test_update_rejects_future_founded_year():
    with pytest.raises(ValidationError):
        CompanyProfileUpdate(founded_year=date.today().year + 1)


async def test_profiles_are_isolated_per_user(db_session):
    user_a = await _make_user(db_session, kakao_id="company-user-a")
    user_b = await _make_user(db_session, kakao_id="company-user-b")

    await save_my_company_profile(
        payload=CompanyProfileUpdate(representative_name="A대표"),
        current_user=user_a,
        session=db_session,
    )

    b_profile = await get_my_company_profile(current_user=user_b, session=db_session)
    assert b_profile is None  # B는 A 프로필을 보지 못한다

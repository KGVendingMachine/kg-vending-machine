"""tests/test_company_service.py

services/company_service.py 테스트. 프로필 자동 채움의 필드 선택
(_autofill_fields)과 지역 표기 정리(_canonical_region_name)는 순수 함수라
DB 없이 검증한다.
"""

from datetime import date

from app.models.company import CompanyProfile
from app.schemas.business_plan import CompanyInfo, NormalizedBusinessPlanSchema
from app.services.company_service import _autofill_fields, _canonical_region_name


def _normalized(**company_kwargs) -> NormalizedBusinessPlanSchema:
    return NormalizedBusinessPlanSchema(company=CompanyInfo(**company_kwargs))


def _profile(**kwargs) -> CompanyProfile:
    return CompanyProfile(user_id=1, is_primary=True, **kwargs)


# ---------------------------------------------------------------------------
# _canonical_region_name
# ---------------------------------------------------------------------------


def test_canonical_region_accepts_standard_short_name():
    assert _canonical_region_name("서울") == "서울"


def test_canonical_region_strips_full_address():
    assert _canonical_region_name("서울특별시 강남구 테헤란로") == "서울"
    assert _canonical_region_name("경기도 성남시 분당구") == "경기"
    assert _canonical_region_name("세종특별자치시") == "세종"


def test_canonical_region_maps_full_province_names():
    assert _canonical_region_name("전라북도 전주시") == "전북"
    assert _canonical_region_name("경상남도 창원시") == "경남"
    assert _canonical_region_name("충청북도") == "충북"
    assert _canonical_region_name("강원특별자치도 춘천시") == "강원"


def test_canonical_region_returns_none_for_unknown():
    assert _canonical_region_name(None) is None
    assert _canonical_region_name("") is None
    assert _canonical_region_name("미국 캘리포니아") is None


# ---------------------------------------------------------------------------
# _autofill_fields
# ---------------------------------------------------------------------------


def test_autofill_fills_empty_profile():
    normalized = _normalized(
        name="주식회사 테스트",
        ceo_name="홍길동",
        founded_year=2021,
        region_name="서울특별시 강남구",
        business_type="법인사업자",
    )

    fields = _autofill_fields(normalized, _profile())

    assert fields == {
        "company_name": "주식회사 테스트",
        "representative_name": "홍길동",
        "founded_date": date(2021, 1, 1),
        "region_name": "서울",
        "region_code": "11",
        "business_type": "법인사업자",
    }


def test_autofill_never_overwrites_existing_values():
    """유저가 이미 입력한 컬럼은 정규화 결과가 달라도 그대로 둔다."""
    normalized = _normalized(
        name="다른회사",
        ceo_name="김철수",
        founded_year=2019,
        region_name="부산",
        business_type="개인사업자",
    )
    profile = _profile(
        company_name="원래회사",
        representative_name="홍길동",
        founded_date=date(2021, 1, 1),
        region_name="서울",
        region_code="11",
        business_type="법인사업자",
    )

    assert _autofill_fields(normalized, profile) == {}


def test_autofill_skips_invalid_values():
    """enum 밖 사업자유형·범위 밖 설립연도·미확인 지역은 채우지 않는다."""
    normalized = _normalized(
        founded_year=2100,
        region_name="실리콘밸리",
        business_type="주식회사",
    )

    assert _autofill_fields(normalized, _profile()) == {}


def test_autofill_drops_pre_founder_when_founding_evidence_exists():
    """예비창업자 추출값은 설립연도 등 설립 이력과 공존할 수 없어 버린다."""
    normalized = _normalized(business_type="예비창업자", founded_year=2021)

    fields = _autofill_fields(normalized, _profile())

    assert "business_type" not in fields
    assert fields["founded_date"] == date(2021, 1, 1)


def test_autofill_drops_pre_founder_when_profile_has_registration():
    normalized = _normalized(business_type="예비창업자")
    profile = _profile(business_registration_number="000-00-00000")

    assert "business_type" not in _autofill_fields(normalized, profile)


def test_autofill_allows_pre_founder_without_conflicts():
    normalized = _normalized(business_type="예비창업자")

    fields = _autofill_fields(normalized, _profile())

    assert fields["business_type"] == "예비창업자"

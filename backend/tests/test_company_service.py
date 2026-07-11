"""tests/test_company_service.py

services/company_service.py 테스트. is_profile_complete는 순수 함수라
DB 없이 검증한다.
"""

from app.models.company import CompanyProfile
from app.services.company_service import is_profile_complete


def test_is_profile_complete_false_when_profile_missing():
    assert is_profile_complete(None) is False


def test_is_profile_complete_false_when_all_fields_blank():
    profile = CompanyProfile(user_id=1, is_primary=True)

    assert is_profile_complete(profile) is False


def test_is_profile_complete_true_when_representative_name_set():
    profile = CompanyProfile(user_id=1, is_primary=True, representative_name="홍길동")

    assert is_profile_complete(profile) is True


def test_is_profile_complete_true_when_business_registration_number_set():
    profile = CompanyProfile(
        user_id=1, is_primary=True, business_registration_number="000-00-00000"
    )

    assert is_profile_complete(profile) is True

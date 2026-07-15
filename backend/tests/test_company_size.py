"""tests/test_company_size.py

업종·매출 기반 기업 규모 파생(services/company_size.derive_company_size) 검증.
"""

from app.services.company_size import derive_company_size

_BILLION = 100_000_000


def test_none_revenue_is_unknown():
    """매출을 모르면 한쪽으로 단정하지 않고 None(모름)."""
    assert derive_company_size("C", None) is None
    assert derive_company_size(None, None) is None


def test_at_or_below_industry_ceiling_is_sme():
    # 제조업(C) 상한 1,000억: 딱 상한이면 중소기업(경계 포함)
    assert derive_company_size("C", 1000 * _BILLION) == "중소기업"
    assert derive_company_size("C", 50 * _BILLION) == "중소기업"


def test_above_industry_ceiling_is_non_sme():
    # 정보통신(J) 상한 600억: 초과하면 중견기업
    assert derive_company_size("J", 700 * _BILLION) == "중견기업"


def test_ceiling_differs_by_industry():
    """같은 매출이라도 업종 상한이 달라 판정이 갈린다."""
    revenue = 500 * _BILLION
    assert derive_company_size("C", revenue) == "중소기업"  # 제조업 상한 1,000억
    assert derive_company_size("I", revenue) == "중견기업"  # 숙박·음식점 상한 400억


def test_unknown_industry_uses_lenient_default():
    """업종 미입력이면 관대한 기본 상한(1,000억)을 적용한다."""
    assert derive_company_size(None, 1000 * _BILLION) == "중소기업"
    assert derive_company_size("", 1001 * _BILLION) == "중견기업"

"""업력 축 파싱/판정 순수 함수 검증 (DB 불필요)."""

from app.services.notice_business_years import (
    notice_allows_company,
    parse_biz_enyy,
)

# --- parse_biz_enyy (해석 A: 누적 상한) ---


def test_parse_single_ceiling():
    assert parse_biz_enyy("7년미만") == (False, 7)


def test_parse_prestartup_only():
    assert parse_biz_enyy("예비창업자") == (True, None)


def test_parse_prestartup_with_full_ladder():
    value = "예비창업자,1년미만,2년미만,3년미만,5년미만,7년미만,10년미만"
    assert parse_biz_enyy(value) == (True, 10)


def test_parse_ceilings_take_max_not_first():
    # 나열 순서와 무관하게 최댓값을 상한으로 본다.
    assert parse_biz_enyy("1년미만,2년미만,3년미만,5년미만,7년미만") == (False, 7)


def test_parse_prestartup_and_single_ceiling():
    assert parse_biz_enyy("예비창업자,7년미만") == (True, 7)


def test_parse_empty_or_none_is_no_restriction():
    assert parse_biz_enyy("") is None
    assert parse_biz_enyy(None) is None


def test_parse_unknown_tokens_are_no_restriction():
    # 인식 못 하는 토큰만 있으면 제한 정보로 취급하지 않는다(permissive).
    assert parse_biz_enyy("전국,기타") is None


# --- notice_allows_company (기업 판정) ---


def test_no_restriction_passes_everyone():
    # target_allows_prestartup is None = biz_enyy 없음 → permissive.
    assert notice_allows_company(
        target_allows_prestartup=None,
        max_years=None,
        is_prestartup=False,
        business_years=99,
    )


def test_prestartup_company_needs_prestartup_notice():
    assert notice_allows_company(
        target_allows_prestartup=True,
        max_years=None,
        is_prestartup=True,
        business_years=None,
    )
    assert not notice_allows_company(
        target_allows_prestartup=False,
        max_years=7,
        is_prestartup=True,
        business_years=None,
    )


def test_founded_company_under_ceiling_passes():
    assert notice_allows_company(
        target_allows_prestartup=False,
        max_years=7,
        is_prestartup=False,
        business_years=3,
    )


def test_founded_company_at_or_over_ceiling_fails():
    # "N년미만"은 미만이므로 업력 == 상한도 탈락.
    assert not notice_allows_company(
        target_allows_prestartup=False,
        max_years=7,
        is_prestartup=False,
        business_years=7,
    )
    assert not notice_allows_company(
        target_allows_prestartup=False,
        max_years=7,
        is_prestartup=False,
        business_years=10,
    )


def test_founded_company_blocked_when_notice_is_prestartup_only():
    # 공고가 예비창업자만 대상(max_years is None)이면 기창업은 탈락.
    assert not notice_allows_company(
        target_allows_prestartup=True,
        max_years=None,
        is_prestartup=False,
        business_years=1,
    )


def test_founded_company_unknown_years_passes_permissive():
    # 업력을 못 구하고 예비도 아니면 업력 축 permissive 통과.
    assert notice_allows_company(
        target_allows_prestartup=False,
        max_years=7,
        is_prestartup=False,
        business_years=None,
    )

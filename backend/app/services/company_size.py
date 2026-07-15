"""기업 규모(중소기업 여부) 파생.

사용자가 소기업/중기업/중견을 스스로 정확히 고르기 어려운 문제 때문에,
규모를 직접 입력받지 않고 업종(KSIC 대분류)과 연매출로 산출한다. 기준은
중소기업기본법 시행령 별표1(2015년 매출액 단일기준 개편)이다.

지금은 "중소기업으로 크게만" 필터링이 목표라 중소기업/중견기업 2단계로만
판정한다. 소상공인/소기업/중기업 세분은 상시근로자 수까지 함께 봐야 하므로
정밀 필터가 필요해질 때 같은 입력값(업종·근로자수·매출)으로 확장한다.

한계: KSIC 대분류(A~S) 단위로만 받으므로 별표의 세부 업종별 상한을 대분류
대표값으로 근사한다. 한 대분류 안에 상한이 다른 세부 업종이 섞인 경우(특히
제조업 C는 세부 업종별로 800~1,500억 혼재) 경계 매출에서 오분류가 날 수 있다.
"""

_BILLION = 100_000_000  # 1억(원)

# 중소기업 매출액(3년 평균) 상한 — KSIC 대분류별 근사값, 단위: 원.
_SME_REVENUE_CEILING_BY_INDUSTRY: dict[str, int] = {
    "A": 1000 * _BILLION,  # 농업·임업·어업
    "B": 1000 * _BILLION,  # 광업
    "C": 1000 * _BILLION,  # 제조업 (세부 800~1,500 혼재, 대표 1,000)
    "D": 1000 * _BILLION,  # 전기·가스·증기
    "E": 800 * _BILLION,  # 수도·하수·폐기물
    "F": 800 * _BILLION,  # 건설업
    "G": 1000 * _BILLION,  # 도매·소매
    "H": 800 * _BILLION,  # 운수·창고
    "I": 400 * _BILLION,  # 숙박·음식점
    "J": 600 * _BILLION,  # 정보통신
    "K": 400 * _BILLION,  # 금융·보험
    "L": 400 * _BILLION,  # 부동산
    "M": 600 * _BILLION,  # 전문·과학·기술
    "N": 600 * _BILLION,  # 사업시설관리·사업지원·임대
    "P": 400 * _BILLION,  # 교육 서비스
    "Q": 600 * _BILLION,  # 보건·사회복지
    "R": 600 * _BILLION,  # 예술·스포츠·여가
    "S": 400 * _BILLION,  # 협회·단체·수리·기타 개인 서비스
}

# 업종 미입력 시 적용할 기본 상한. 실제 중소기업을 중견으로 잘못 거르는
# 것보다 관대하게 통과시키는 쪽이 안전해서(놓치는 방향이 아니라 더 넓게
# 인정) 대분류 상한 중 가장 높은 1,000억을 쓴다.
_DEFAULT_SME_REVENUE_CEILING = 1000 * _BILLION

SME = "중소기업"
NON_SME = "중견기업"


def derive_company_size(
    industry_code: str | None, annual_revenue: int | None
) -> str | None:
    """업종과 연매출로 '중소기업' / '중견기업'을 판정한다.

    매출을 모르면 판정할 수 없어 None(모름)을 반환한다 — 매칭 단계
    (matching_service._eligibility_score)에서 company_size가 None이면 규모
    불일치로 감점하지 않고 관대하게 처리되므로, 억지로 한쪽으로 단정하지
    않는다.
    """
    if annual_revenue is None:
        return None
    ceiling = _SME_REVENUE_CEILING_BY_INDUSTRY.get(
        industry_code or "", _DEFAULT_SME_REVENUE_CEILING
    )
    return SME if annual_revenue <= ceiling else NON_SME

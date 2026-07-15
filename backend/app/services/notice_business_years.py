"""업력(業歷) 축 — K-Startup `biz_enyy` 파싱과 기업 업력 판정.

공고측 `biz_enyy`는 콤마 구분 토큰이다: `예비창업자` + `N년미만`(1·2·3·5·7·10).
수집 시 이 원문을 구조화해 notice 컬럼(`target_allows_prestartup`,
`target_business_years_max`)에 저장하고(=`parse_biz_enyy`), 1차 필터는 그
컬럼만 보고 기업을 판정한다(=`notice_allows_company`). 파싱과 판정을 한
모듈에 둔 이유는 "상한(누적 상한, 해석 A)"의 의미가 두 쪽에서 어긋나지
않게 하기 위해서다.

해석 A(누적 상한): 작성자마다 "상한만(`7년미만`)" 적기도 하고 "전부 나열
(`1,2,3,5,7년미만`)"하기도 해 일관성이 없다. 그래서 나열된 `N년미만` 중
최댓값을 업력 상한으로 본다. 자세한 근거·리스크는 docs/first-filtering.md §3③.
"""

import re

# "N년미만" 토큰에서 N을 뽑는다. biz_enyy 실측값은 1/2/3/5/7/10년미만.
_YEAR_CEILING_RE = re.compile(r"^(\d+)\s*년\s*미만$")
_PRESTARTUP_TOKEN = "예비창업자"


def parse_biz_enyy(value: str | None) -> tuple[bool, int | None] | None:
    """K-Startup `biz_enyy` 원문을 `(allow_prestartup, max_years)`로 구조화한다.

    - `allow_prestartup`: 공고가 예비창업자를 대상에 포함하는가.
    - `max_years`: 기창업 허용 업력 상한(년). `N년미만` 중 최댓값. `예비창업자`
      만 있으면 None(기창업 대상 아님).
    - 반환값 None: 업력 제한 정보가 없음(빈값이거나 인식 가능한 토큰이 하나도
      없음) → 필터에서 permissive 통과. 컬럼도 NULL로 두라는 신호.

    예) `7년미만`→(False, 7), `예비창업자`→(True, None),
        `예비창업자,1년미만,...,10년미만`→(True, 10), ``/None→None.
    """
    if not value:
        return None

    tokens = [part.strip() for part in re.split(r"[,;|\r\n]+", value) if part.strip()]
    allow_prestartup = _PRESTARTUP_TOKEN in tokens
    year_ceilings = [
        int(m.group(1)) for t in tokens if (m := _YEAR_CEILING_RE.match(t))
    ]
    max_years = max(year_ceilings) if year_ceilings else None

    # 예비창업자도 없고 인식 가능한 업력 토큰도 없으면(미지의 값) 제한
    # 정보로 취급하지 않는다 — 오탈락을 막는 permissive 원칙.
    if not allow_prestartup and max_years is None:
        return None
    return allow_prestartup, max_years


def notice_allows_company(
    *,
    target_allows_prestartup: bool | None,
    max_years: int | None,
    is_prestartup: bool,
    business_years: int | None,
) -> bool:
    """공고의 업력 제한(구조화 컬럼)을 기업 업력과 대조해 통과 여부를 판정한다.

    - `target_allows_prestartup is None`: 공고에 업력 제한 정보 없음
      (biz_enyy 없음/미백필) → permissive 통과.
    - 예비창업 기업: 공고가 예비창업자를 허용할 때만 통과.
    - 기창업 기업: 업력을 못 구하면 permissive 통과. 공고가 예비창업자
      전용(max_years is None)이면 탈락. 그 외 `업력 < max_years`면 통과.
    """
    if target_allows_prestartup is None:
        return True
    if is_prestartup:
        return target_allows_prestartup
    if business_years is None:
        return True
    if max_years is None:
        return False
    return business_years < max_years

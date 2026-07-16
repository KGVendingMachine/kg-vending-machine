"""1차 필터링(기업 기준 공고 하드필터).

기업 프로필을 입력으로 하드필터를 통과한 notice.id 목록과 축별 탈락 집계를
반환한다. 축은 4개: ①지역 ②대상(신청주체) ③업력 ④기간. 자세한 설계·근거는
docs/first-filtering.md.

핵심 원칙(전부 permissive): 공고에 해당 축 제한이 없거나 기업측 값이 없으면
그 축에서는 탈락시키지 않는다. 제한이 "있을 때"만 대조해 탈락시킨다.

matching_service의 _eligibility_score(감점형 soft)와 목적이 다르다 — 이쪽은
명시적 탈락 후 id 목록 반환(hard)이다.
"""

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import CompanyProfile
from app.repositories.business_plan_repository import get_latest_by_company_profile
from app.repositories.notice_eligibility_repository import (
    NoticeEligibilityRow,
    get_eligibility_candidates,
)
from app.services.applicant_type_filter import passes_applicant_type_filter
from app.services.notice_business_years import notice_allows_company

logger = logging.getLogger(__name__)

# 기업측 예비창업 판정에 쓰는 값들.
_PRESTARTUP_BUSINESS_TYPE = "예비창업자"
_PRESTARTUP_STAGE = "예비창업자"


@dataclass(frozen=True)
class EligibilityResult:
    notice_ids: list[int]
    counts: dict[str, int]


# --- 축별 순수 판정 ---


def passes_region(
    notice_region_codes: frozenset[str], company_region_code: str | None
) -> bool:
    """지역 축. 기업 지역코드가 없거나(필터 불가) 공고에 지역 제한이 없으면
    통과. 공고가 전국(ALL)이거나 기업 지역을 포함하면 통과."""
    if not company_region_code:
        return True
    if not notice_region_codes:
        return True
    if "ALL" in notice_region_codes:
        return True
    return company_region_code in notice_region_codes


def passes_period(
    status: str | None,
    start_date: date | None,
    end_date: date | None,
    today: date,
) -> bool:
    """기간 축(당일 기준). status가 '모집중'이거나, 신청시작일이 지났고
    (종료일이 없거나 아직 안 지났으면) 통과. status 낡음의 영향을 줄이려
    날짜도 직접 본다(docs/first-filtering.md §3④)."""
    if status == "모집중":
        return True
    if start_date is not None and start_date <= today:
        return end_date is None or end_date >= today
    return False


def _passes_all_axes(
    row: NoticeEligibilityRow,
    *,
    region_code: str | None,
    business_type: str | None,
    is_prestartup: bool,
    business_years: int | None,
    today: date,
) -> str | None:
    """행이 탈락하는 첫 축의 counts 키를 반환한다. 통과면 None.

    축 순서 = ①지역 ②대상 ③업력 ④기간 (docs/first-filtering.md). 순차로
    처음 걸리는 축에서 멈춰 그 축의 탈락으로 집계한다."""
    if not passes_region(row.region_codes, region_code):
        return "지역_탈락"
    if not passes_applicant_type_filter(list(row.target_types), business_type):
        return "대상_탈락"
    if not notice_allows_company(
        target_allows_prestartup=row.target_allows_prestartup,
        max_years=row.target_business_years_max,
        is_prestartup=is_prestartup,
        business_years=business_years,
    ):
        return "업력_탈락"
    if not passes_period(
        row.status, row.application_start_date, row.application_end_date, today
    ):
        return "기간_탈락"
    return None


# --- 기업측 값 도출 ---


def _full_years(founded: date, today: date) -> int:
    """설립일 기준 만 업력(년, 내림). 생일 안 지났으면 1 뺀다."""
    years = today.year - founded.year
    if (today.month, today.day) < (founded.month, founded.day):
        years -= 1
    return max(0, years)


def _derive_is_prestartup(
    business_type: str | None,
    company_stage: str | None,
    registration_status: str | None,
) -> bool:
    """기업이 예비창업(사업자등록 전)인지. 프로필 값이 없으면 사업계획서
    분석값(business_registration_status)에 '예비' 신호가 있는지로 폴백."""
    if business_type == _PRESTARTUP_BUSINESS_TYPE:
        return True
    if company_stage == _PRESTARTUP_STAGE:
        return True
    if registration_status and "예비" in registration_status:
        return True
    return False


def _derive_business_years(
    business_years: int | None,
    founded_date: date | None,
    founded_year: int | None,
    today: date,
) -> int | None:
    """기업 업력(년). company_profile.business_years 우선, 없으면 설립일로
    계산, 그래도 없으면 사업계획서 분석값 founded_year로 폴백. 전부 없으면
    None(업력 축 permissive 통과)."""
    if business_years is not None:
        return business_years
    if founded_date is not None:
        return _full_years(founded_date, today)
    if founded_year is not None:
        return max(0, today.year - founded_year)
    return None


def _needs_analysis_fallback(profile: CompanyProfile) -> bool:
    """사업계획서 분석값 폴백이 필요한지. 업력도, 예비/사업자 단서도 프로필에
    없을 때만 사업계획서를 읽는다(불필요한 조회 회피)."""
    missing_years = profile.business_years is None and profile.founded_date is None
    missing_stage = profile.business_type is None and profile.company_stage is None
    return missing_years or missing_stage


async def get_eligible_notices(
    session: AsyncSession,
    profile: CompanyProfile,
    today: date | None = None,
) -> EligibilityResult:
    """기업 프로필로 하드필터를 통과한 notice.id 목록과 축별 집계를 반환한다."""
    today = today or date.today()

    company_analysis: dict = {}
    if _needs_analysis_fallback(profile):
        plan = await get_latest_by_company_profile(session, profile.id)
        analysis_json = plan.analysis_json if plan else None
        if isinstance(analysis_json, dict):
            company = analysis_json.get("company")
            if isinstance(company, dict):
                company_analysis = company
        # 프로필에 업력/사업자 단서가 없어 사업계획서 분석값으로 폴백한
        # 경로. 뒤 결과가 예상과 다를 때 "값이 어디서 왔나"를 알려준다.
        logger.debug(
            "1차 필터 업력/예비 값 폴백 시도 (profile_id=%s): plan=%s, "
            "founded_year=%s, registration_status=%s",
            profile.id,
            "있음" if plan else "없음",
            company_analysis.get("founded_year"),
            company_analysis.get("business_registration_status"),
        )

    is_prestartup = _derive_is_prestartup(
        profile.business_type,
        profile.company_stage,
        company_analysis.get("business_registration_status"),
    )
    business_years = _derive_business_years(
        profile.business_years,
        profile.founded_date,
        company_analysis.get("founded_year"),
        today,
    )

    candidates = await get_eligibility_candidates(session)
    counts = {
        "input": len(candidates),
        "지역_탈락": 0,
        "대상_탈락": 0,
        "업력_탈락": 0,
        "기간_탈락": 0,
        "통과": 0,
    }
    notice_ids: list[int] = []
    for row in candidates:
        rejected_axis = _passes_all_axes(
            row,
            region_code=profile.region_code,
            business_type=profile.business_type,
            is_prestartup=is_prestartup,
            business_years=business_years,
            today=today,
        )
        if rejected_axis is None:
            notice_ids.append(row.notice_id)
            counts["통과"] += 1
        else:
            counts[rejected_axis] += 1

    # 도출된 기업 입력값 + 축별 퍼널을 한 줄로. 결과가 이상할 때(너무 적게/
    # 많이 통과) 어느 축에서 걸렸고 기업 값이 뭐였는지 바로 보이게 한다.
    logger.info(
        "1차 필터 완료 (profile_id=%s): region=%s, is_prestartup=%s, "
        "business_years=%s | input=%d → 통과=%d "
        "(지역_탈락=%d, 대상_탈락=%d, 업력_탈락=%d, 기간_탈락=%d)",
        profile.id,
        profile.region_code,
        is_prestartup,
        business_years,
        counts["input"],
        counts["통과"],
        counts["지역_탈락"],
        counts["대상_탈락"],
        counts["업력_탈락"],
        counts["기간_탈락"],
    )

    return EligibilityResult(notice_ids=notice_ids, counts=counts)

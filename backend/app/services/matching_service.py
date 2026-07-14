from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_plan import BusinessPlan
from app.models.company import CompanyProfile
from app.models.match import MatchLog, MatchResult
from app.models.notice import Notice
from app.repositories import match_log_repository
from app.schemas.business_plan import NormalizedBusinessPlanSchema
from app.schemas.notice_normalization import NormalizedNoticeSchema

logger = logging.getLogger(__name__)

_QUALITY_REQUIRED_FIELDS: tuple[str, ...] = (
    "basic.title",
    "support.summary",
    "support.support_type",
    "support.support_content",
    "matching.keywords",
    "matching.suitable_company_profile",
    "matching.matching_signals",
)

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(억원|억|천만원|백만원|만원|원)")
_ALL_REGIONS = {"전국", "ALL", "all", "전체", "전 지역", "nationwide"}
_KRW_UNITS = {
    "억원": 100_000_000,
    "억": 100_000_000,
    "천만원": 10_000_000,
    "백만원": 1_000_000,
    "만원": 10_000,
    "원": 1,
}


class MatchingNotReadyError(Exception):
    """매칭을 실행할 수 있는 공고가 없어 점수 산출이 불가능할 때 발생.

    정규화된 공고가 아예 없거나(수집만 되고 정규화 배치를 안 돌린 상태),
    전부 품질 기준 미달인 경우다. 사용자가 아니라 운영 쪽에서 공고 정규화를
    돌려야 해결되므로, 빈 결과로 조용히 완료하지 않고 명시적으로 실패시킨다.
    """


@dataclass(frozen=True)
class ScoredNotice:
    notice: Notice
    result: MatchResult


@dataclass(frozen=True)
class FilterDecision:
    stage: str
    status: str
    reasons: tuple[str, ...] = ()

    @property
    def dropped(self) -> bool:
        return self.status == "drop"

    def to_json(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class PipelineCandidate:
    notice: Notice
    normalized_notice: NormalizedNoticeSchema
    first_stage: FilterDecision
    second_stage: FilterDecision


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(value).strip()]


def _join_values(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            parts.append(_join_values(*value.values()))
        elif isinstance(value, list):
            parts.append(_join_values(*value))
        else:
            parts.append(str(value))
    return " ".join(part for part in parts if part)


def _tokens(*values: Any) -> set[str]:
    text = _join_values(*values).lower()
    return {token for token in _TOKEN_RE.findall(text) if len(token) >= 2}


def _overlap_score(left: set[str], right: set[str], *, default: float = 50.0) -> float:
    if not left or not right:
        return default
    overlap = len(left & right)
    base = min(len(left), len(right))
    if base == 0:
        return default
    return min(100.0, 35.0 + (overlap / base) * 65.0)


def _extract_krw_amounts(text: str | None) -> list[int]:
    if not text:
        return []
    amounts: list[int] = []
    for value, unit in _AMOUNT_RE.findall(text.replace(",", "")):
        amounts.append(int(float(value) * _KRW_UNITS[unit]))
    return amounts


def _max_krw_amount(text: str | None) -> int | None:
    amounts = _extract_krw_amounts(text)
    return max(amounts) if amounts else None


def _industry_candidate_tokens(plan: NormalizedBusinessPlanSchema) -> set[str]:
    values: list[Any] = [plan.company.industry]
    for candidate in plan.company.industry_candidates:
        values.extend(
            [
                candidate.label,
                candidate.reason,
                candidate.source_keywords,
            ]
        )
    return _tokens(*values)


def _field_match_result(
    plan: NormalizedBusinessPlanSchema,
    normalized_notice: NormalizedNoticeSchema,
) -> tuple[float, dict[str, Any]]:
    candidate_tokens = _industry_candidate_tokens(plan)
    notice_tokens = _tokens(
        normalized_notice.basic.category,
        normalized_notice.support.support_type,
        normalized_notice.support.support_content,
        normalized_notice.eligibility.target_industries,
        normalized_notice.matching.keywords,
        normalized_notice.matching.matching_signals,
    )
    score = _overlap_score(candidate_tokens, notice_tokens)
    matched_fields = sorted(candidate_tokens & notice_tokens)[:20]
    has_candidates = bool(plan.company.industry_candidates)

    if matched_fields:
        status = "matched"
        reason = (
            "사업 분야 후보가 공고의 분야, 지원 내용 또는 매칭 키워드와 일치합니다."
        )
    elif has_candidates:
        status = "needs_review"
        reason = "사업 분야 후보와 공고의 분야 신호가 명확히 일치하지 않아 추가 검토가 필요합니다."
    else:
        status = "fallback"
        reason = "구조화된 사업 분야 후보가 없어 기업 업종과 사업계획서 본문 정보를 기준으로 검토했습니다."

    return score, {
        "status": status,
        "score": round(score, 2),
        "matched_fields": matched_fields,
        "industry_candidates": [
            {
                "label": candidate.label,
                "confidence": candidate.confidence,
                "reason": candidate.reason,
                "source_keywords": candidate.source_keywords,
            }
            for candidate in plan.company.industry_candidates
        ],
        "reason": reason,
    }


def _contains_any(text: str | None, candidates: list[str]) -> bool:
    if not text:
        return False
    return any(candidate in text for candidate in candidates if candidate)


def _get_path(data: dict[str, Any], path: str) -> Any:
    value: Any = data
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | dict):
        return bool(value)
    return True


def _quality_errors(notice_json: dict[str, Any]) -> list[str]:
    return [
        field_path
        for field_path in _QUALITY_REQUIRED_FIELDS
        if not _has_value(_get_path(notice_json, field_path))
    ]


def _parse_business_plan(plan: BusinessPlan) -> NormalizedBusinessPlanSchema:
    return NormalizedBusinessPlanSchema.model_validate(plan.analysis_json or {})


def _parse_notice(notice: Notice) -> NormalizedNoticeSchema | None:
    if not notice.normalized_json:
        return None
    return NormalizedNoticeSchema.model_validate(notice.normalized_json)


def _notice_field_tokens(normalized_notice: NormalizedNoticeSchema) -> set[str]:
    return _tokens(
        normalized_notice.basic.category,
        normalized_notice.eligibility.target_industries,
        normalized_notice.matching.keywords,
        normalized_notice.matching.matching_signals,
    )


def _is_all_region(value: str) -> bool:
    return value.strip() in _ALL_REGIONS


def _region_matches(profile_region: str | None, target_regions: list[str]) -> bool:
    if not target_regions or any(_is_all_region(region) for region in target_regions):
        return True
    if not profile_region:
        return False
    return _contains_any(profile_region, target_regions)


def _first_stage_filter(
    *,
    plan: NormalizedBusinessPlanSchema,
    profile: CompanyProfile,
    notice: Notice,
    normalized_notice: NormalizedNoticeSchema,
    today: date | None = None,
) -> FilterDecision:
    reasons: list[str] = []
    pass_reasons: list[str] = []
    review_reasons: list[str] = []
    today = today or date.today()

    if notice.application_end_date and notice.application_end_date < today:
        reasons.append("신청 마감일이 지난 공고입니다.")
    elif notice.application_end_date:
        pass_reasons.append("신청 마감일이 지나지 않은 공고입니다.")
    else:
        review_reasons.append("신청 마감일 정보가 없어 제외하지 않았습니다.")

    target_regions = normalized_notice.eligibility.target_regions
    if not target_regions or any(_is_all_region(region) for region in target_regions):
        pass_reasons.append("공고의 지원 지역이 전국 대상이거나 지역 제한이 없습니다.")
    else:
        if profile.region_name:
            if not _region_matches(profile.region_name, target_regions):
                reasons.append("기업 소재지가 공고의 지원 지역과 명확히 다릅니다.")
            else:
                pass_reasons.append("기업 소재지가 공고의 지원 지역 조건과 일치합니다.")
        else:
            review_reasons.append(
                "기업 소재지 정보가 없어 지역 조건은 검토 대상으로 남깁니다."
            )

    industry_tokens = _industry_candidate_tokens(plan)
    notice_field_tokens = _notice_field_tokens(normalized_notice)
    has_structured_notice_industries = bool(
        normalized_notice.eligibility.target_industries
    )
    has_structured_plan_industries = bool(plan.company.industry_candidates)
    if (
        has_structured_plan_industries
        and has_structured_notice_industries
        and industry_tokens
        and notice_field_tokens
        and not (industry_tokens & notice_field_tokens)
    ):
        reasons.append(
            "사업 분야 후보가 공고의 대상 업종/분야와 명확히 일치하지 않습니다."
        )
    elif industry_tokens & notice_field_tokens:
        matched_fields = ", ".join(sorted(industry_tokens & notice_field_tokens)[:5])
        pass_reasons.append(
            f"사업 분야 후보와 공고 분야 키워드가 일치합니다: {matched_fields}"
        )
    elif not industry_tokens or not notice_field_tokens:
        review_reasons.append(
            "분야 비교에 필요한 구조화 정보가 부족해 제외하지 않았습니다."
        )

    required_status = normalized_notice.eligibility.required_status
    if required_status and profile.business_type:
        if not _contains_any(profile.business_type, required_status):
            reasons.append("기업 형태가 공고의 필수 지원대상과 명확히 다릅니다.")
        else:
            pass_reasons.append("기업 형태가 공고의 필수 지원대상 조건과 일치합니다.")
    elif required_status:
        review_reasons.append(
            "기업 형태 정보가 없어 필수 지원대상은 검토 대상으로 남깁니다."
        )
    else:
        pass_reasons.append("공고에 별도 기업 형태 제한이 없습니다.")

    if reasons:
        return FilterDecision("first_stage", "drop", tuple(reasons))
    if review_reasons:
        return FilterDecision(
            "first_stage",
            "review",
            tuple(pass_reasons + review_reasons),
        )
    return FilterDecision("first_stage", "pass", tuple(pass_reasons))


def _second_stage_filter(
    *,
    plan: NormalizedBusinessPlanSchema,
    profile: CompanyProfile,
    notice: Notice,
    normalized_notice: NormalizedNoticeSchema,
) -> FilterDecision:
    reasons: list[str] = []
    pass_reasons: list[str] = []
    review_reasons: list[str] = []

    target_sizes = normalized_notice.eligibility.target_company_size
    if target_sizes and profile.company_size:
        if not _contains_any(profile.company_size, target_sizes) and not any(
            "기업" in size for size in target_sizes
        ):
            reasons.append("기업 규모가 공고의 정량 지원 조건과 명확히 다릅니다.")
        else:
            pass_reasons.append("기업 규모가 공고의 지원 대상 조건과 일치합니다.")
    elif target_sizes:
        review_reasons.append(
            "기업 규모 정보가 없어 정량 조건은 검토 대상으로 남깁니다."
        )
    else:
        pass_reasons.append("공고에 별도 기업 규모 제한이 없습니다.")

    age_min = normalized_notice.eligibility.business_age_min
    age_max = (
        normalized_notice.eligibility.business_age_max
        if normalized_notice.eligibility.business_age_max is not None
        else notice.target_business_years_max
    )
    if profile.business_years is not None:
        if age_min is not None and profile.business_years < age_min:
            reasons.append("기업 업력이 공고의 최소 업력 조건보다 짧습니다.")
        if age_max is not None and profile.business_years > age_max:
            reasons.append("기업 업력이 공고의 최대 업력 조건을 초과합니다.")
        if not reasons and (age_min is not None or age_max is not None):
            pass_reasons.append("기업 업력이 공고의 업력 조건 범위에 포함됩니다.")
    elif age_min is not None or age_max is not None:
        review_reasons.append(
            "기업 업력 정보가 없어 업력 조건은 검토 대상으로 남깁니다."
        )
    else:
        pass_reasons.append("공고에 별도 업력 제한이 없습니다.")

    support_amount = normalized_notice.support.support_amount
    if support_amount:
        support_amount_max = _max_krw_amount(support_amount)
        requested_amount = plan.funding.amount_requested
        if support_amount_max is None:
            review_reasons.append(
                "지원금액 조건은 원문 표현이 다양해 현재는 검토 정보로만 남깁니다."
            )
        elif requested_amount is not None and requested_amount > support_amount_max:
            review_reasons.append(
                "사업계획서 요청 금액이 공고 지원 한도보다 클 수 있어 확인이 필요합니다."
            )
        elif requested_amount is None:
            review_reasons.append(
                "사업계획서 요청 금액 정보가 없어 지원금액 조건은 검토 대상으로 남깁니다."
            )
        else:
            pass_reasons.append("사업계획서 요청 금액이 공고 지원 한도 이내입니다.")
    else:
        review_reasons.append(
            "공고 지원금액 정보가 없어 금액 조건은 검토 대상으로 남깁니다."
        )

    if reasons:
        return FilterDecision("second_stage", "drop", tuple(reasons))
    if review_reasons:
        return FilterDecision(
            "second_stage",
            "review",
            tuple(pass_reasons + review_reasons),
        )
    return FilterDecision("second_stage", "pass", tuple(pass_reasons))


def _count_decisions(decisions: list[FilterDecision]) -> dict[str, int]:
    counts = {"pass": 0, "review": 0, "drop": 0}
    for decision in decisions:
        if decision.status in counts:
            counts[decision.status] += 1
    return counts


def _summarize_reasons(decisions: list[FilterDecision]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for decision in decisions:
        for reason in decision.reasons:
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def _build_pipeline_summary(
    *,
    input_count: int,
    quality_failed: dict[int, list[str]],
    parse_failed_ids: list[int],
    first_stage_decisions: list[FilterDecision],
    second_stage_decisions: list[FilterDecision],
    scored: list[ScoredNotice],
    selected: list[MatchResult],
) -> dict[str, Any]:
    quality_passed = input_count - len(quality_failed) - len(parse_failed_ids)
    return {
        "input_count": input_count,
        "quality_filter": {
            "passed_count": quality_passed,
            "dropped_count": len(quality_failed) + len(parse_failed_ids),
            "missing_field_counts": _quality_missing_field_counts(quality_failed),
            "parse_failed_notice_ids": parse_failed_ids,
        },
        "first_stage_filter": {
            **_count_decisions(first_stage_decisions),
            "reason_counts": _summarize_reasons(first_stage_decisions),
        },
        "second_stage_filter": {
            **_count_decisions(second_stage_decisions),
            "reason_counts": _summarize_reasons(second_stage_decisions),
        },
        "scoring": {
            "scored_count": len(scored),
            "selected_count": len(selected),
            "selected_notice_ids": [result.notice_id for result in selected],
        },
    }


def _quality_missing_field_counts(
    quality_failed: dict[int, list[str]],
) -> dict[str, int]:
    missing_field_counts: dict[str, int] = {}
    for errors in quality_failed.values():
        for field_path in errors:
            missing_field_counts[field_path] = (
                missing_field_counts.get(field_path, 0) + 1
            )
    return missing_field_counts


def _eligibility_score(
    profile: CompanyProfile, notice: NormalizedNoticeSchema
) -> tuple[float, str, list[str]]:
    score = 55.0
    reasons: list[str] = []
    cautions: list[str] = []

    target_regions = notice.eligibility.target_regions
    if not target_regions or set(target_regions) & _ALL_REGIONS:
        score += 15
        reasons.append("지원 지역 제한이 없거나 전국 대상입니다.")
    elif profile.region_name and _contains_any(profile.region_name, target_regions):
        score += 20
        reasons.append("기업 소재지가 공고의 지원 지역과 일치합니다.")
    else:
        score -= 15
        cautions.append(
            "기업 소재지가 공고의 지원 지역 조건과 맞는지 확인이 필요합니다."
        )

    target_sizes = notice.eligibility.target_company_size
    if not target_sizes:
        score += 5
    elif profile.company_size and _contains_any(profile.company_size, target_sizes):
        score += 15
        reasons.append("기업 규모가 공고의 지원 대상과 일치합니다.")
    elif any("기업" in size for size in target_sizes):
        score += 8
        reasons.append("공고의 기업 규모 조건이 비교적 넓게 해석될 수 있습니다.")
    else:
        score -= 10
        cautions.append("기업 규모가 공고의 지원 대상 조건과 맞는지 확인이 필요합니다.")

    target_stages = notice.eligibility.target_business_stage
    if not target_stages:
        score += 5
    elif profile.company_stage and _contains_any(profile.company_stage, target_stages):
        score += 10
        reasons.append("기업 성장 단계가 공고의 지원 대상과 일치합니다.")

    if notice.eligibility.excluded_targets:
        cautions.extend(
            f"제외 대상 확인 필요: {target}"
            for target in notice.eligibility.excluded_targets[:2]
        )

    score = max(0.0, min(100.0, score))
    if score >= 75:
        status = "eligible"
    elif score >= 50:
        status = "needs_review"
    else:
        status = "likely_ineligible"
    return score, status, cautions


def _score_notice(
    *,
    plan: NormalizedBusinessPlanSchema,
    profile: CompanyProfile,
    notice: Notice,
    normalized_notice: NormalizedNoticeSchema,
    first_stage: FilterDecision | None = None,
    second_stage: FilterDecision | None = None,
) -> MatchResult:
    plan_item_tokens = _tokens(
        plan.company.industry,
        plan.problem.background,
        plan.problem.target_customer_pain_point,
        plan.problem.market_problem,
        plan.solution.summary,
        plan.solution.product_description,
        plan.solution.tech_stack,
        plan.solution.differentiators,
        plan.market.target_market,
        plan.market.target_customer_persona,
    )
    plan_growth_tokens = _tokens(
        plan.funding.scale_up_strategy,
        plan.funding.use_of_funds,
        plan.team.capabilities,
    )
    notice_item_tokens = _tokens(
        normalized_notice.basic.category,
        normalized_notice.support.support_type,
        normalized_notice.support.support_content,
        normalized_notice.eligibility.target_industries,
        normalized_notice.matching.keywords,
    )
    notice_matching_tokens = _tokens(
        normalized_notice.support.summary,
        normalized_notice.matching.suitable_company_profile,
        normalized_notice.matching.matching_signals,
        normalized_notice.evaluation.criteria,
        normalized_notice.evaluation.preferred_conditions,
    )

    eligibility_score, eligibility_status, cautions = _eligibility_score(
        profile, normalized_notice
    )
    field_match_score, field_match = _field_match_result(plan, normalized_notice)
    base_item_fit_score = _overlap_score(plan_item_tokens, notice_item_tokens)
    item_fit_score = (base_item_fit_score * 0.70) + (field_match_score * 0.30)
    business_fit_score = _overlap_score(plan_item_tokens, notice_matching_tokens)
    growth_score = _overlap_score(plan_growth_tokens, notice_matching_tokens)
    bonus_score = _overlap_score(
        _tokens(plan.solution.differentiators, plan.team.capabilities),
        _tokens(normalized_notice.evaluation.preferred_conditions),
        default=45.0,
    )

    total_score = (
        eligibility_score * 0.30
        + item_fit_score * 0.25
        + business_fit_score * 0.25
        + growth_score * 0.15
        + bonus_score * 0.05
    )
    if eligibility_status == "likely_ineligible":
        total_score = min(total_score, 49.0)

    recommendation_level = _recommendation_level(total_score)
    strengths = _strengths(
        item_fit_score=item_fit_score,
        business_fit_score=business_fit_score,
        growth_score=growth_score,
    )
    weakness = _weakness(cautions, item_fit_score, business_fit_score)
    strategy = _strategy_suggestion(normalized_notice, growth_score)

    result_json = {
        "pipeline_filters": {
            "first_stage": first_stage.to_json() if first_stage else None,
            "second_stage": second_stage.to_json() if second_stage else None,
        },
        "notice_quality": {"status": "passed", "missing_fields": []},
        "field_match": field_match,
        "score_breakdown": {
            "eligibility": round(eligibility_score, 2),
            "item_fit": round(item_fit_score, 2),
            "item_fit_base": round(base_item_fit_score, 2),
            "field_match": round(field_match_score, 2),
            "business_fit": round(business_fit_score, 2),
            "growth": round(growth_score, 2),
            "bonus": round(bonus_score, 2),
        },
        "matched_keywords": sorted(plan_item_tokens & notice_item_tokens)[:20],
        "match_reasons": strengths,
        "eligibility_check": {
            "status": eligibility_status,
            "score": round(eligibility_score, 2),
            "cautions": cautions,
            "target_regions": normalized_notice.eligibility.target_regions,
            "target_company_size": normalized_notice.eligibility.target_company_size,
            "target_business_stage": normalized_notice.eligibility.target_business_stage,
            "target_industries": normalized_notice.eligibility.target_industries,
        },
        "cautions": cautions + normalized_notice.matching.caution_points[:3],
        "suggested_actions": [strategy] if strategy else [],
    }

    return MatchResult(
        notice_id=notice.id,
        total_score=_decimal(total_score),
        eligibility_score=_decimal(eligibility_score),
        item_fit_score=_decimal(item_fit_score),
        business_fit_score=_decimal(business_fit_score),
        growth_score=_decimal(growth_score),
        bonus_score=_decimal(bonus_score),
        eligibility_status=eligibility_status,
        recommendation_level=recommendation_level,
        summary_reason="; ".join(strengths),
        weakness=weakness,
        strategy_suggestion=strategy,
        result_json=result_json,
    )


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 2)))


def _recommendation_level(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 65:
        return "recommended"
    if score >= 50:
        return "normal"
    return "low"


def _strengths(
    *, item_fit_score: float, business_fit_score: float, growth_score: float
) -> list[str]:
    strengths: list[str] = []
    if item_fit_score >= 65:
        strengths.append("사업 아이템이 공고의 핵심 키워드와 잘 맞습니다.")
    if business_fit_score >= 65:
        strengths.append("사업계획서 내용이 공고의 선호 조건과 잘 맞습니다.")
    if growth_score >= 65:
        strengths.append("성장 전략이 지원사업의 목적과 잘 연결됩니다.")
    if not strengths:
        strengths.append("기본 지원 요건을 기준으로 추가 검토가 필요합니다.")
    return strengths


def _weakness(
    cautions: list[str], item_fit_score: float, business_fit_score: float
) -> str | None:
    weakness: list[str] = []
    weakness.extend(cautions[:3])
    if item_fit_score < 50:
        weakness.append("사업 아이템과 공고 분야의 직접적인 연결 근거가 부족합니다.")
    if business_fit_score < 50:
        weakness.append("사업계획서 내용과 공고 선호 조건의 연결 근거가 부족합니다.")
    return "; ".join(weakness) if weakness else None


def _strategy_suggestion(
    notice: NormalizedNoticeSchema, growth_score: float
) -> str | None:
    if growth_score >= 65:
        return "신청서에서 성장 전략과 기대 성과를 구체적으로 강조하는 것이 좋습니다."
    if notice.evaluation.criteria:
        return f"평가 기준({', '.join(notice.evaluation.criteria[:3])})에 맞춰 사업 내용을 보강하는 것이 좋습니다."
    return "지원 자격과 기대 성과를 뒷받침할 수 있는 근거를 더 명확히 제시하는 것이 좋습니다."


async def run_matching(
    session: AsyncSession,
    *,
    log: MatchLog,
    plan: BusinessPlan,
    profile: CompanyProfile,
    max_results: int,
) -> list[MatchResult]:
    normalized_plan = _parse_business_plan(plan)
    candidates = await match_log_repository.list_normalized_notice_candidates(session)
    logger.info(
        "매칭 시작 (match_log_id=%s, business_plan_id=%s): 정규화 완료 후보 공고 %d건",
        log.id,
        plan.id,
        len(candidates),
    )

    if not candidates:
        logger.warning(
            "매칭 불가 (match_log_id=%s): 정규화 완료된 공고가 0건 — 공고 정규화"
            " 배치(POST /internal/notices/normalize/batch)를 먼저 실행해야 한다",
            log.id,
        )
        raise MatchingNotReadyError(
            "매칭할 수 있는 공고가 없습니다. 공고 정규화가 완료된 뒤 다시 시도해주세요."
        )

    quality_failed: dict[int, list[str]] = {}
    parse_failed_ids: list[int] = []
    first_stage_decisions: list[FilterDecision] = []
    second_stage_decisions: list[FilterDecision] = []

    parsed_candidates: list[tuple[Notice, NormalizedNoticeSchema]] = []
    for notice in candidates:
        quality_errors = _quality_errors(notice.normalized_json or {})
        if quality_errors:
            quality_failed[notice.id] = quality_errors
            continue

        try:
            normalized_notice = _parse_notice(notice)
        except ValidationError:
            parse_failed_ids.append(notice.id)
            continue
        if normalized_notice is None:
            parse_failed_ids.append(notice.id)
            continue
        parsed_candidates.append((notice, normalized_notice))

    first_stage_candidates: list[tuple[Notice, NormalizedNoticeSchema, FilterDecision]]
    first_stage_candidates = []
    for notice, normalized_notice in parsed_candidates:
        decision = _first_stage_filter(
            plan=normalized_plan,
            profile=profile,
            notice=notice,
            normalized_notice=normalized_notice,
        )
        first_stage_decisions.append(decision)
        if not decision.dropped:
            first_stage_candidates.append((notice, normalized_notice, decision))

    pipeline_candidates: list[PipelineCandidate] = []
    for notice, normalized_notice, first_stage in first_stage_candidates:
        second_stage = _second_stage_filter(
            plan=normalized_plan,
            profile=profile,
            notice=notice,
            normalized_notice=normalized_notice,
        )
        second_stage_decisions.append(second_stage)
        if not second_stage.dropped:
            pipeline_candidates.append(
                PipelineCandidate(
                    notice=notice,
                    normalized_notice=normalized_notice,
                    first_stage=first_stage,
                    second_stage=second_stage,
                )
            )

    if not pipeline_candidates:
        log.query_json = {
            "business_plan": plan.analysis_json,
            "pipeline": _build_pipeline_summary(
                input_count=len(candidates),
                quality_failed=quality_failed,
                parse_failed_ids=parse_failed_ids,
                first_stage_decisions=first_stage_decisions,
                second_stage_decisions=second_stage_decisions,
                scored=[],
                selected=[],
            ),
        }
        logger.warning(
            "매칭 불가 (match_log_id=%s): 후보 %d건 전부 필터링 단계에서 제외",
            log.id,
            len(candidates),
        )
        raise MatchingNotReadyError(
            "매칭 기준을 충족하는 공고가 없습니다. 필터링 조건과 공고 정규화 품질을 확인해주세요."
        )

    scored: list[ScoredNotice] = []
    eligibility_counts: dict[str, int] = {
        "eligible": 0,
        "needs_review": 0,
        "likely_ineligible": 0,
    }
    for candidate in pipeline_candidates:
        result = _score_notice(
            plan=normalized_plan,
            profile=profile,
            notice=candidate.notice,
            normalized_notice=candidate.normalized_notice,
            first_stage=candidate.first_stage,
            second_stage=candidate.second_stage,
        )
        result.recommendation_run_id = log.id
        if result.eligibility_status in eligibility_counts:
            eligibility_counts[result.eligibility_status] += 1
        scored.append(ScoredNotice(notice=candidate.notice, result=result))
        logger.debug(
            "공고 %s 점수: total=%s (자격=%s/아이템=%s/사업화=%s/성장=%s/가점=%s,"
            " 자격상태=%s, 일치키워드=%s)",
            candidate.notice.id,
            result.total_score,
            result.eligibility_score,
            result.item_fit_score,
            result.business_fit_score,
            result.growth_score,
            result.bonus_score,
            result.eligibility_status,
            (result.result_json or {}).get("matched_keywords"),
        )

    scored.sort(key=lambda item: item.result.total_score or Decimal("0"), reverse=True)
    selected = [item.result for item in scored[:max_results]]
    pipeline_summary = _build_pipeline_summary(
        input_count=len(candidates),
        quality_failed=quality_failed,
        parse_failed_ids=parse_failed_ids,
        first_stage_decisions=first_stage_decisions,
        second_stage_decisions=second_stage_decisions,
        scored=scored,
        selected=selected,
    )
    log.query_json = {
        "business_plan": plan.analysis_json,
        "pipeline": pipeline_summary,
    }

    logger.info(
        "품질 필터 [match_log_id=%s]: 입력 %d건 중 통과 %d건, 제외 %d건",
        log.id,
        len(candidates),
        pipeline_summary["quality_filter"]["passed_count"],
        pipeline_summary["quality_filter"]["dropped_count"],
    )
    if quality_failed:
        logger.info(
            "품질 필터 [match_log_id=%s] 제외 사유별 건수: %s",
            log.id,
            pipeline_summary["quality_filter"]["missing_field_counts"],
        )
    if parse_failed_ids:
        logger.info(
            "품질 필터 [match_log_id=%s] 정규화 스키마 파싱 실패로 추가 제외: "
            "%d건 (notice_id=%s)",
            log.id,
            len(parse_failed_ids),
            parse_failed_ids,
        )
    logger.info(
        "1차 필터링 [match_log_id=%s]: pass=%d, review=%d, drop=%d, 사유=%s",
        log.id,
        pipeline_summary["first_stage_filter"]["pass"],
        pipeline_summary["first_stage_filter"]["review"],
        pipeline_summary["first_stage_filter"]["drop"],
        pipeline_summary["first_stage_filter"]["reason_counts"],
    )
    logger.info(
        "2차 필터링 [match_log_id=%s]: pass=%d, review=%d, drop=%d, 사유=%s",
        log.id,
        pipeline_summary["second_stage_filter"]["pass"],
        pipeline_summary["second_stage_filter"]["review"],
        pipeline_summary["second_stage_filter"]["drop"],
        pipeline_summary["second_stage_filter"]["reason_counts"],
    )
    logger.info(
        "스코어링 [match_log_id=%s] 자격요건 분포: eligible=%d, "
        "needs_review=%d, likely_ineligible=%d (likely_ineligible은 총점 49점 캡)",
        log.id,
        eligibility_counts["eligible"],
        eligibility_counts["needs_review"],
        eligibility_counts["likely_ineligible"],
    )

    await match_log_repository.replace_results(session, log.id, selected)

    log.run_status = "completed"
    log.completed_at = _now_naive()
    logger.info(
        "매칭 완료 (match_log_id=%s): 점수 산출 %d건 중 상위 %d건 저장 — %s",
        log.id,
        len(scored),
        len(selected),
        [
            (
                item.notice.id,
                str(item.result.total_score),
                item.result.recommendation_level,
            )
            for item in scored[:max_results]
        ],
    )
    return selected

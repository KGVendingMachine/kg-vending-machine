from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

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
_ALL_REGIONS = {"전국", "ALL", "all", "전체", "전 지역", "nationwide"}


@dataclass(frozen=True)
class ScoredNotice:
    notice: Notice
    result: MatchResult


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


def _eligibility_score(
    profile: CompanyProfile, notice: NormalizedNoticeSchema
) -> tuple[float, str, list[str]]:
    score = 55.0
    reasons: list[str] = []
    cautions: list[str] = []

    target_regions = notice.eligibility.target_regions
    if not target_regions or set(target_regions) & _ALL_REGIONS:
        score += 15
        reasons.append("region open")
    elif profile.region_name and _contains_any(profile.region_name, target_regions):
        score += 20
        reasons.append("region matched")
    else:
        score -= 15
        cautions.append("region needs review")

    target_sizes = notice.eligibility.target_company_size
    if not target_sizes:
        score += 5
    elif profile.company_size and _contains_any(profile.company_size, target_sizes):
        score += 15
        reasons.append("company size matched")
    elif any("기업" in size for size in target_sizes):
        score += 8
        reasons.append("company target broadly matched")
    else:
        score -= 10
        cautions.append("company size needs review")

    target_stages = notice.eligibility.target_business_stage
    if not target_stages:
        score += 5
    elif profile.company_stage and _contains_any(profile.company_stage, target_stages):
        score += 10
        reasons.append("business stage matched")

    if notice.eligibility.excluded_targets:
        cautions.extend(
            f"excluded target: {target}"
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
    item_fit_score = _overlap_score(plan_item_tokens, notice_item_tokens)
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
        "notice_quality": {"status": "passed", "missing_fields": []},
        "score_breakdown": {
            "eligibility": round(eligibility_score, 2),
            "item_fit": round(item_fit_score, 2),
            "business_fit": round(business_fit_score, 2),
            "growth": round(growth_score, 2),
            "bonus": round(bonus_score, 2),
        },
        "matched_keywords": sorted(plan_item_tokens & notice_item_tokens)[:20],
        "cautions": cautions + normalized_notice.matching.caution_points[:3],
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
        strengths.append("business item matches notice keywords")
    if business_fit_score >= 65:
        strengths.append("business plan matches notice signals")
    if growth_score >= 65:
        strengths.append("growth strategy aligns with support purpose")
    if not strengths:
        strengths.append("basic eligibility can be reviewed")
    return strengths


def _weakness(
    cautions: list[str], item_fit_score: float, business_fit_score: float
) -> str | None:
    weakness: list[str] = []
    weakness.extend(cautions[:3])
    if item_fit_score < 50:
        weakness.append("item fit evidence is weak")
    if business_fit_score < 50:
        weakness.append("business-plan fit evidence is weak")
    return "; ".join(weakness) if weakness else None


def _strategy_suggestion(
    notice: NormalizedNoticeSchema, growth_score: float
) -> str | None:
    if growth_score >= 65:
        return "Emphasize the scale-up plan and expected business outcome."
    if notice.evaluation.criteria:
        return (
            f"Address evaluation criteria: {', '.join(notice.evaluation.criteria[:3])}."
        )
    return "Add clearer evidence for eligibility and expected support outcomes."


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

    # docs/matching-pipeline.md "로깅 요구사항" — 1차 필터링(품질 필터 +
    # 자격요건 필터) 단계는 별도 엔드포인트 없이 이 루프 안에 통합돼 있어,
    # 어느 기준에서 몇 건이 걸러졌는지는 로그로만 추적할 수 있다.
    quality_excluded_ids: list[int] = []
    quality_missing_field_counts: dict[str, int] = {}
    parse_failed_ids: list[int] = []
    eligibility_counts: dict[str, int] = {
        "eligible": 0,
        "needs_review": 0,
        "likely_ineligible": 0,
    }

    scored: list[ScoredNotice] = []
    for notice in candidates:
        quality_errors = _quality_errors(notice.normalized_json or {})
        if quality_errors:
            quality_excluded_ids.append(notice.id)
            for field_path in quality_errors:
                quality_missing_field_counts[field_path] = (
                    quality_missing_field_counts.get(field_path, 0) + 1
                )
            continue

        normalized_notice = _parse_notice(notice)
        if normalized_notice is None:
            parse_failed_ids.append(notice.id)
            continue

        result = _score_notice(
            plan=normalized_plan,
            profile=profile,
            notice=notice,
            normalized_notice=normalized_notice,
        )
        result.recommendation_run_id = log.id
        if result.eligibility_status in eligibility_counts:
            eligibility_counts[result.eligibility_status] += 1
        scored.append(ScoredNotice(notice=notice, result=result))

    scored.sort(key=lambda item: item.result.total_score or Decimal("0"), reverse=True)
    selected = [item.result for item in scored[:max_results]]

    logger.info(
        "1차 필터링 [match_log_id=%s] 품질 필터: 입력 %d건 중 통과 %d건, 제외 %d건",
        log.id,
        len(candidates),
        len(candidates) - len(quality_excluded_ids),
        len(quality_excluded_ids),
    )
    if quality_missing_field_counts:
        logger.info(
            "1차 필터링 [match_log_id=%s] 품질 필터 제외 사유별 건수: %s",
            log.id,
            quality_missing_field_counts,
        )
    if parse_failed_ids:
        logger.info(
            "1차 필터링 [match_log_id=%s] 정규화 스키마 파싱 실패로 추가 제외: "
            "%d건 (notice_id=%s)",
            log.id,
            len(parse_failed_ids),
            parse_failed_ids,
        )
    logger.info(
        "1차 필터링 [match_log_id=%s] 자격요건 필터 분포 (통과 %d건 중): "
        "eligible=%d, needs_review=%d, likely_ineligible=%d"
        " (likely_ineligible은 제외 대신 총점 49점 캡)",
        log.id,
        len(scored),
        eligibility_counts["eligible"],
        eligibility_counts["needs_review"],
        eligibility_counts["likely_ineligible"],
    )
    logger.info(
        "1차 필터링 [match_log_id=%s] 완료: 필터 통과 %d건 중 상위 %d건 선정, "
        "notice_id=%s",
        log.id,
        len(scored),
        len(selected),
        [item.notice_id for item in selected],
    )

    await match_log_repository.replace_results(session, log.id, selected)

    log.run_status = "completed"
    log.completed_at = _now_naive()
    return selected

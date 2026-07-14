from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.business_plan import BusinessPlan
from app.models.company import CompanyProfile
from app.models.match import MatchLog, MatchResult
from app.models.notice import Notice
from app.repositories import match_log_repository
from app.schemas.business_plan import NormalizedBusinessPlanSchema
from app.schemas.notice_normalization import NormalizedNoticeSchema
from app.services.secondary_filtering_judge_service import (
    JudgedSecondaryScore,
    judge_notice,
)
from app.services.secondary_filtering_service import (
    SecondaryFilteringResult,
    run_secondary_filtering,
)

logger = logging.getLogger(__name__)

# LLM 판정(secondary_filtering_judge_service.judge_notice)은 공고당 OpenAI 호출
# 1회라 비용·지연이 크므로, 1차 필터링 통과 후보 전부가 아니라 임베딩 유사도
# 상위 K건에만 돌린다(docs/secondary-filtering-llm-judge-guide.md TBD #1,
# bizSupportNavigator rag_search의 limit과 같은 이유). 상위 K건 밖의 임베딩된
# 공고는 판정 없이 기존 코사인 유사도 점수를 그대로 쓴다.
_SECONDARY_FILTERING_JUDGE_TOP_K = 15

_secondary_filtering_judge_semaphore = asyncio.Semaphore(
    get_settings().SECONDARY_FILTERING_JUDGE_CONCURRENCY_LIMIT
)

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


def _eligibility_score(
    profile: CompanyProfile, notice: NormalizedNoticeSchema
) -> tuple[float, str, list[str]]:
    score = 55.0
    cautions: list[str] = []

    target_regions = notice.eligibility.target_regions
    if not target_regions or set(target_regions) & _ALL_REGIONS:
        score += 15
    elif profile.region_name and _contains_any(profile.region_name, target_regions):
        score += 20
    else:
        score -= 15
        cautions.append(
            f"사업장 지역({profile.region_name or '미등록'})이 공고 대상 지역"
            f"({', '.join(target_regions)})과 달라 확인이 필요합니다."
        )

    target_sizes = notice.eligibility.target_company_size
    if not target_sizes:
        score += 5
    elif profile.company_size and _contains_any(profile.company_size, target_sizes):
        score += 15
    elif any("기업" in size for size in target_sizes):
        score += 8
    else:
        score -= 10
        cautions.append(
            f"기업 규모({profile.company_size or '미등록'})가 공고 대상 규모"
            f"({', '.join(target_sizes)})와 달라 확인이 필요합니다."
        )

    target_stages = notice.eligibility.target_business_stage
    if not target_stages:
        score += 5
    elif profile.company_stage and _contains_any(profile.company_stage, target_stages):
        score += 10

    if notice.eligibility.excluded_targets:
        cautions.extend(
            f"제외 대상 해당 여부 확인 필요: {target}"
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
    secondary_filter_score: float | None = None,
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
    # 2차 필터링 점수(secondary_filtering_service의 임베딩 유사도, 유사도
    # 상위 후보는 secondary_filtering_judge_service의 LLM 판정 점수로 대체됨)
    # 근거가 없는 공고(첨부파일 없음, 임베딩 실패, 판정 대상 요건 없음 등)는
    # 페널티 없이 중립값(_overlap_score의 default=50.0과 같은 기준)으로 채운다.
    resolved_secondary_score = (
        secondary_filter_score if secondary_filter_score is not None else 50.0
    )

    total_score = (
        eligibility_score * 0.25
        + item_fit_score * 0.20
        + business_fit_score * 0.20
        + growth_score * 0.10
        + bonus_score * 0.05
        + resolved_secondary_score * 0.20
    )
    if eligibility_status == "likely_ineligible":
        total_score = min(total_score, 49.0)

    matched_keywords = sorted(plan_item_tokens & notice_item_tokens)[:20]

    recommendation_level = _recommendation_level(total_score)
    strengths = _strengths(
        item_fit_score=item_fit_score,
        business_fit_score=business_fit_score,
        growth_score=growth_score,
        matched_keywords=matched_keywords,
    )
    weakness = _weakness(cautions, item_fit_score, business_fit_score)
    strategy = _strategy_suggestion(normalized_notice, growth_score)

    logger.info(
        "🧠 AI 정밀 판정 근거 (notice_id=%s): 💪 강점=%s | ⚠️ 주의=%s | 💡 제안=%s",
        notice.id,
        strengths,
        weakness,
        strategy,
    )

    result_json = {
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
            "secondary_filter": round(resolved_secondary_score, 2),
        },
        "secondary_filter_available": secondary_filter_score is not None,
        "matched_keywords": matched_keywords,
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
    *,
    item_fit_score: float,
    business_fit_score: float,
    growth_score: float,
    matched_keywords: list[str],
) -> list[str]:
    strengths: list[str] = []
    if item_fit_score >= 65:
        if matched_keywords:
            sample = ", ".join(matched_keywords[:3])
            strengths.append(
                f"사업 아이템이 공고 키워드({sample} 등)와 일치합니다"
                f" (아이템 적합도 {item_fit_score:.0f}점)."
            )
        else:
            strengths.append(
                f"사업 아이템 적합도가 {item_fit_score:.0f}점으로 높게 나타났습니다."
            )
    if business_fit_score >= 65:
        strengths.append(
            f"사업계획서 내용이 공고의 지원 시그널과 잘 맞습니다"
            f" (사업 정합성 {business_fit_score:.0f}점)."
        )
    if growth_score >= 65:
        strengths.append(
            f"성장 전략이 공고의 지원 목적과 부합합니다 (성장성 {growth_score:.0f}점)."
        )
    if not strengths:
        strengths.append(
            f"아이템 적합도 {item_fit_score:.0f}점 · 사업 정합성 {business_fit_score:.0f}점 · "
            f"성장성 {growth_score:.0f}점으로, 기본 자격요건 수준에서 검토가 가능합니다."
        )
    return strengths


def _weakness(
    cautions: list[str], item_fit_score: float, business_fit_score: float
) -> str | None:
    weakness: list[str] = []
    weakness.extend(cautions[:3])
    if item_fit_score < 50:
        weakness.append(
            f"아이템 적합도가 {item_fit_score:.0f}점으로 낮아 관련 근거 보완이 필요합니다."
        )
    if business_fit_score < 50:
        weakness.append(
            f"사업 정합성이 {business_fit_score:.0f}점으로 낮아 사업계획서 내용 보완이 필요합니다."
        )
    return "; ".join(weakness) if weakness else None


def _strategy_suggestion(
    notice: NormalizedNoticeSchema, growth_score: float
) -> str | None:
    if growth_score >= 65:
        return f"성장성 {growth_score:.0f}점 — 사업화 확장 계획과 기대 효과를 강조하면 좋습니다."
    if notice.evaluation.criteria:
        return (
            f"다음 평가 기준을 보완하세요: {', '.join(notice.evaluation.criteria[:3])}."
        )
    return (
        f"성장성이 {growth_score:.0f}점으로 낮습니다 — 자격요건 충족 근거와 기대 지원 성과를"
        " 더 명확히 제시하세요."
    )


async def _judge_top_candidates(
    *,
    log_id: int,
    plan: NormalizedBusinessPlanSchema,
    profile: CompanyProfile,
    secondary_result: SecondaryFilteringResult,
    passed: list[tuple[Notice, NormalizedNoticeSchema]],
) -> tuple[dict[int, float], dict[int, JudgedSecondaryScore]]:
    """secondary_result.scores(코사인 유사도)로 순위를 매겨 상위
    _SECONDARY_FILTERING_JUDGE_TOP_K건만 judge_notice()로 정밀 판정하고,
    최종 secondary_filter_score(판정된 공고는 판정 점수, 나머지는 기존
    유사도 점수)와 판정 근거를 반환한다.
    """
    final_scores = dict(secondary_result.scores)
    judged_by_notice: dict[int, JudgedSecondaryScore] = {}

    ranked_notice_ids = sorted(
        secondary_result.scores,
        key=lambda notice_id: secondary_result.scores[notice_id],
        reverse=True,
    )[:_SECONDARY_FILTERING_JUDGE_TOP_K]
    if not ranked_notice_ids:
        return final_scores, judged_by_notice

    notice_by_id = {notice.id: (notice, normalized) for notice, normalized in passed}

    async def _judge_one(notice_id: int) -> None:
        _, normalized_notice = notice_by_id[notice_id]
        async with _secondary_filtering_judge_semaphore:
            judged = await judge_notice(
                profile=profile,
                plan=plan,
                notice=normalized_notice,
                evidence=secondary_result.evidence.get(notice_id, []),
            )
        if judged is not None:
            final_scores[notice_id] = judged.score
            judged_by_notice[notice_id] = judged

    await asyncio.gather(*(_judge_one(notice_id) for notice_id in ranked_notice_ids))

    logger.info(
        "2차 필터링 LLM 판정 [match_log_id=%s] 완료: 유사도 상위 %d건 중 판정 "
        "%d건 (나머지는 정규화 단계에서 판정 가능한 자격/제외 요건이 없어 "
        "유사도 점수를 그대로 사용)",
        log_id,
        len(ranked_notice_ids),
        len(judged_by_notice),
    )
    return final_scores, judged_by_notice


def _build_secondary_filtering_log(
    *,
    passed: list[tuple[Notice, NormalizedNoticeSchema]],
    secondary_result: SecondaryFilteringResult,
    final_scores: dict[int, float],
    judgments: dict[int, JudgedSecondaryScore],
) -> dict[str, Any]:
    """2차 필터링 실행 로그를 match_log.secondary_filtering_log(JSONB)에 저장할
    형태로 만든다. GET /match-logs/{id}/secondary-filtering가 그대로 반환한다.

    docs/matching-pipeline.md 로깅 요구사항(2차 필터링: OCR 대상 공고 수,
    임베딩 실패 건수, 유사도 점수 상/하위 분포, 최종 확정 공고 ID)을
    구조화해 남긴다 — 서버 로그(logger.info)만으로는 실행이 끝난 뒤 특정
    match_log의 2차 필터링 근거를 다시 조회할 수 없기 때문이다.

    similarity_score(코사인 유사도, 판정 대상 선별에 쓰인 값)와
    secondary_filter_score(실제 total_score에 반영된 최종값 — 판정된
    공고는 LLM 판정 점수, 나머지는 similarity_score와 동일)를 분리해서
    남긴다 — 왜 이 공고가 판정 대상으로 뽑혔고 판정 후 점수가 어떻게
    바뀌었는지 둘 다 추적할 수 있어야 하기 때문이다.
    """
    similarity_scores = secondary_result.scores
    skip_reasons = {skip.notice_id: skip.reason for skip in secondary_result.skips}

    notices = [
        {
            "notice_id": notice.id,
            "title": notice.title,
            "embedded": notice.id in similarity_scores,
            "similarity_score": similarity_scores.get(notice.id),
            "llm_judged": notice.id in judgments,
            "secondary_filter_score": final_scores.get(notice.id),
            "excluded": (
                judgments[notice.id].excluded if notice.id in judgments else False
            ),
            "reasons": (
                [
                    {
                        "criterion": judgment.criterion,
                        "status": judgment.status,
                        "evidence": judgment.evidence,
                        "is_exclusion": judgment.is_exclusion,
                    }
                    for judgment in judgments[notice.id].judgments
                ]
                if notice.id in judgments
                else []
            ),
            "skip_reason": skip_reasons.get(notice.id),
        }
        for notice, _ in passed
    ]
    notices.sort(
        key=lambda item: (
            item["secondary_filter_score"] is None,
            -(item["secondary_filter_score"] or 0),
        )
    )

    score_values = list(final_scores.values())
    score_stats = (
        {
            "min": round(min(score_values), 2),
            "max": round(max(score_values), 2),
            "avg": round(sum(score_values) / len(score_values), 2),
        }
        if score_values
        else None
    )

    return {
        "plan_embedded": secondary_result.plan_embedded,
        "plan_skip_reason": secondary_result.plan_skip_reason,
        "candidate_count": len(passed),
        "embedded_count": len(similarity_scores),
        "judged_count": len(judgments),
        "skipped_count": len(passed) - len(similarity_scores),
        "score_stats": score_stats,
        "notices": notices,
    }


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

    # docs/matching-pipeline.md "로깅 요구사항" — 1차 필터링(품질 필터 +
    # 자격요건 필터) 단계는 별도 엔드포인트 없이 이 루프 안에 통합돼 있어,
    # 어느 기준에서 몇 건이 걸러졌는지는 로그로만 추적할 수 있다.
    quality_failed: dict[int, list[str]] = {}
    parse_failed_ids: list[int] = []
    eligibility_counts: dict[str, int] = {
        "eligible": 0,
        "needs_review": 0,
        "likely_ineligible": 0,
    }

    passed: list[tuple[Notice, NormalizedNoticeSchema]] = []
    for notice in candidates:
        quality_errors = _quality_errors(notice.normalized_json or {})
        if quality_errors:
            quality_failed[notice.id] = quality_errors
            continue

        normalized_notice = _parse_notice(notice)
        if normalized_notice is None:
            parse_failed_ids.append(notice.id)
            continue

        passed.append((notice, normalized_notice))

    if not passed:
        logger.warning(
            "매칭 불가 (match_log_id=%s): 후보 %d건 전부 품질 기준 미달 또는 파싱 실패",
            log.id,
            len(candidates),
        )
        raise MatchingNotReadyError(
            "매칭 기준을 충족하는 공고가 없습니다. 공고 정규화 품질을 확인해주세요."
        )

    # 2차 필터링(docs/matching-pipeline.md 4단계) — 1차 필터링(품질+자격요건)을
    # 통과한 후보에 한해서만 공고 PDF 임베딩·유사도 검색을 수행한다(전체
    # 후보를 다 임베딩하면 비용이 크므로, 3단계에서 명백히 무관한 공고를
    # 먼저 제거하는 것과 같은 이유). 임베딩이 없거나 실패한 공고는 결과에서
    # 빠지고 _score_notice가 중립값으로 처리한다.
    secondary_result = await run_secondary_filtering(
        session,
        business_plan_id=plan.id,
        candidate_notice_ids=[notice.id for notice, _ in passed],
    )
    # 유사도 상위 K건만 LLM으로 정밀 판정한다(docs/secondary-filtering-llm-judge-guide.md)
    # — final_scores는 판정된 공고는 판정 점수, 나머지는 기존 유사도 점수를 담는다.
    final_secondary_scores, secondary_judgments = await _judge_top_candidates(
        log_id=log.id,
        plan=normalized_plan,
        profile=profile,
        secondary_result=secondary_result,
        passed=passed,
    )

    scored: list[ScoredNotice] = []
    for notice, normalized_notice in passed:
        result = _score_notice(
            plan=normalized_plan,
            profile=profile,
            notice=notice,
            normalized_notice=normalized_notice,
            secondary_filter_score=final_secondary_scores.get(notice.id),
        )
        result.recommendation_run_id = log.id
        if result.eligibility_status in eligibility_counts:
            eligibility_counts[result.eligibility_status] += 1
        scored.append(ScoredNotice(notice=notice, result=result))
        logger.debug(
            "공고 %s 점수: total=%s (자격=%s/아이템=%s/사업화=%s/성장=%s/가점=%s/"
            "2차필터링=%s, 자격상태=%s, 일치키워드=%s)",
            notice.id,
            result.total_score,
            result.eligibility_score,
            result.item_fit_score,
            result.business_fit_score,
            result.growth_score,
            result.bonus_score,
            final_secondary_scores.get(notice.id),
            result.eligibility_status,
            (result.result_json or {}).get("matched_keywords"),
        )

    log.secondary_filtering_log = _build_secondary_filtering_log(
        passed=passed,
        secondary_result=secondary_result,
        final_scores=final_secondary_scores,
        judgments=secondary_judgments,
    )
    logger.info(
        "2차 필터링 [match_log_id=%s] 완료: 1차 통과 %d건 중 유사도 점수 산출 "
        "%d건, LLM 판정 %d건 (나머지는 중립값 50.0 또는 유사도 점수로 처리)",
        log.id,
        len(passed),
        len(secondary_result.scores),
        len(secondary_judgments),
    )

    scored.sort(key=lambda item: item.result.total_score or Decimal("0"), reverse=True)
    selected = [item.result for item in scored[:max_results]]

    logger.info(
        "1차 필터링 [match_log_id=%s] 품질 필터: 입력 %d건 중 통과 %d건, 제외 %d건",
        log.id,
        len(candidates),
        len(candidates) - len(quality_failed),
        len(quality_failed),
    )
    if quality_failed:
        missing_field_counts: dict[str, int] = {}
        for errors in quality_failed.values():
            for field_path in errors:
                missing_field_counts[field_path] = (
                    missing_field_counts.get(field_path, 0) + 1
                )
        logger.info(
            "1차 필터링 [match_log_id=%s] 품질 필터 제외 사유별 건수: %s",
            log.id,
            missing_field_counts,
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

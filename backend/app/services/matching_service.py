from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.business_plan import BusinessPlan
from app.models.category import CategoryName, KgCategory
from app.models.company import CompanyProfile
from app.models.match import MatchLog, MatchResult
from app.models.notice import Notice
from app.repositories import match_log_repository
from app.repositories.secondary_filtering_judgment_repository import (
    get_cached_judgment,
    save_judgment,
)
from app.schemas.business_plan import NormalizedBusinessPlanSchema
from app.schemas.notice_normalization import NormalizedNoticeSchema
from app.services.company_size import SME as _SME_LABEL
from app.services.notice_eligibility_service import get_eligible_notices
from app.services.secondary_filtering_judge_service import (
    CriterionJudgment,
    JudgedSecondaryScore,
    build_criteria_statements,
    judge_notice,
    profile_fingerprint,
)
from app.services.secondary_filtering_service import (
    SecondaryFilteringResult,
    get_criterion_evidence,
    merge_evidence,
    run_secondary_filtering,
)

logger = logging.getLogger(__name__)

# LLM 판정(secondary_filtering_judge_service.judge_notice)은 공고당 OpenAI 호출
# 1회라 비용·지연이 크므로, 1차 필터링 통과 후보 전부가 아니라 임베딩 유사도
# 상위 K건에만 돌린다(docs/secondary-filtering-llm-judge-guide.md TBD #1,
# bizSupportNavigator rag_search의 limit과 같은 이유). 상위 K건 밖의 임베딩된
# 공고는 판정 없이 기존 코사인 유사도 점수를 그대로 쓴다.
_SECONDARY_FILTERING_JUDGE_TOP_K = 20

# R&D/자금은 유사도가 낮게 나오기 쉬워 전체 후보와 한 풀에서 경쟁하면 top-K
# 밖으로 밀려 LLM 판정을 아예 못 받을 수 있다 — 카테고리 안에서만 따로
# 순위를 매겨 최소 이만큼은 보장한다.
_FIT_CATEGORY_JUDGE_TOP_K = 10

# 종합점수(total_score) 상위 이 순위 안에 든 R&D/자금 공고는, 1차 판정(유사도
# top-K)에서 빠졌더라도 키워드 폴백 점수만으로 최종 노출되지 않도록 재판정한다.
_FINAL_RERANK_JUDGE_TOP_N = 20

_secondary_filtering_judge_semaphore = asyncio.Semaphore(
    get_settings().SECONDARY_FILTERING_JUDGE_CONCURRENCY_LIMIT
)

# bonus(가점)는 나머지 5개와 100%를 나눠 갖지 않는다 — 그러면 가점 기회가
# 없는 공고는 만점이 불가능해지므로, 5개만 100%로 재배분하고 가점은 위에 가산한다.
_DEFAULT_WEIGHTS = {
    "eligibility": 0.30,
    "item_fit": 0.25,
    "business_fit": 0.25,
    "growth": 0.20,
}
# R&D는 평가기준이 기술성·혁신성 위주라 성장성 겹침이 잘 안 잡혀(2026-07-16
# 확인) 성장성 비중을 낮추고 아이템 적합도·2차필터링에 나눠 싣는다.
_RD_WEIGHTS = {
    "eligibility": 0.25,
    "item_fit": 0.35,
    "business_fit": 0.35,
    "growth": 0.05,
}
# 자금(대출·보조금)은 기술/아이템 적합성보다 신용등급·지역·기업규모 같은
# 자격요건 충족 여부가 결정적이라 eligibility 비중을 높이고 item_fit을 낮춘다.
_FUND_WEIGHTS = {
    "eligibility": 0.35,
    "item_fit": 0.15,
    "business_fit": 0.30,
    "growth": 0.20,
}
# 가점은 애매한 점수를 추천 임계값(65) 너머로 살짝 밀어주는 정도가 목적이라
# 핵심 축(20~25%)보다 훨씬 작게 잡는다 — 순위를 가점 하나가 좌우하면 안 된다.
_BONUS_WEIGHT = 0.03

# run_matching() 전체 동시 실행 상한. 매칭 한 건 안에서도 임베딩·LLM 판정이
# 각자 세마포어 한도만큼 동시 호출하므로, 서로 다른 유저의 매칭이 겹치면 그
# 한도가 곱절로 늘어 OpenAI 레이트리밋에 걸린다(match_log.py의 유저별 중복
# 실행 방지와 별개로, 여기서 유저가 달라도 겹치는 것 자체를 막는다).
_matching_pipeline_semaphore = asyncio.Semaphore(
    get_settings().MATCHING_PIPELINE_CONCURRENCY_LIMIT
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

# "중소기업"은 소상공인/소기업/중기업을 포괄하는 상위 개념이라, 공고가 세분
# 값을 요구해도 포괄 일치로 인정한다.
_SME_SUBTIER_LABELS = {"소상공인", "소기업", "중기업", _SME_LABEL}


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


# LLM 판정 문장이 1~2개뿐이면 그 소수 판정 하나로 점수가 0/100으로 극단적으로
# 튄다 — 문장 수가 이 값 이상이어야 LLM 점수를 100% 신뢰하고, 적으면 그만큼
# 키워드 점수를 섞어 완화한다.
_LLM_FULL_CONFIDENCE_CRITERIA_COUNT = 3


def _confidence_blend(
    llm_score: float | None, criteria_count: int, keyword_score: float
) -> tuple[float, bool]:
    """판정 문장 개수로 신뢰도를 매겨 LLM 점수와 키워드 점수를 블렌드한다.
    (점수, LLM이 실제로 반영됐는지) 튜플을 반환한다."""
    if llm_score is None or criteria_count == 0:
        return keyword_score, False
    confidence = min(criteria_count / _LLM_FULL_CONFIDENCE_CRITERIA_COUNT, 1.0)
    return confidence * llm_score + (1 - confidence) * keyword_score, True


def _group_judgment_count(judged: JudgedSecondaryScore | None, group: str) -> int:
    if judged is None:
        return 0
    return sum(1 for j in judged.judgments if j.group == group)


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
) -> tuple[float, str, list[str], list[dict[str, str]]]:
    """소프트 자격요건 점수(감점형, total_score 구성요소).

    run_matching()의 get_eligible_notices()(지역/대상/업력/기간 하드필터,
    docs/first-filtering.md)와 검사 축이 겹치지만 목적이 다르다 — 하드필터는
    통과 못 하면 아예 후보에서 빠지고, 이 함수는 이미 하드필터를 통과한
    공고에 한해 기업규모(company_size, 하드필터가 안 보는 축)까지 포함해
    감점형으로 재차 점수를 매긴다. 중복이 아니라 보완 관계이므로 하드필터
    도입 후에도 그대로 유지한다.

    notes는 cautions(감점 사유만)와 달리 +/− 사유를 모두 담는다 — 화면에
    감점·가점 근거를 같이 보여주기 위함.
    """
    score = 55.0
    cautions: list[str] = []
    notes: list[dict[str, str]] = []

    target_regions = notice.eligibility.target_regions
    if not target_regions or set(target_regions) & _ALL_REGIONS:
        score += 15
        notes.append({"sign": "+", "detail": "전국 대상 공고라 지역 요건에 걸리지 않습니다."})
    elif profile.region_name and _contains_any(profile.region_name, target_regions):
        score += 20
        notes.append(
            {
                "sign": "+",
                "detail": f"사업장 지역({profile.region_name})이 공고 대상 지역과 일치합니다.",
            }
        )
    else:
        score -= 15
        detail = (
            f"사업장 지역({profile.region_name or '미등록'})이 공고 대상 지역"
            f"({', '.join(target_regions)})과 달라 확인이 필요합니다."
        )
        cautions.append(detail)
        notes.append({"sign": "-", "detail": detail})

    target_sizes = notice.eligibility.target_company_size
    if not target_sizes:
        score += 5
        notes.append({"sign": "+", "detail": "기업 규모 제한이 없는 공고입니다."})
    elif profile.company_size and _contains_any(profile.company_size, target_sizes):
        score += 15
        notes.append(
            {
                "sign": "+",
                "detail": f"기업 규모({profile.company_size})가 공고 대상 규모와 일치합니다.",
            }
        )
    elif profile.company_size == _SME_LABEL and any(
        size in _SME_SUBTIER_LABELS for size in target_sizes
    ):
        score += 15
        notes.append(
            {
                "sign": "+",
                "detail": (
                    "기업 규모(중소기업)가 공고 대상 규모(소상공인/소기업/중기업 등"
                    " 중소기업 하위 분류)를 포괄해 일치로 판단했습니다 — 정확한"
                    " 하위 분류는 원문에서 확인이 필요합니다."
                ),
            }
        )
    elif any("기업" in size for size in target_sizes):
        score += 8
        notes.append(
            {"sign": "+", "detail": "공고 대상 규모 표기가 넓어 부분적으로 부합합니다."}
        )
    else:
        score -= 10
        detail = (
            f"기업 규모({profile.company_size or '미등록'})가 공고 대상 규모"
            f"({', '.join(target_sizes)})와 달라 확인이 필요합니다."
        )
        cautions.append(detail)
        notes.append({"sign": "-", "detail": detail})

    target_stages = notice.eligibility.target_business_stage
    if not target_stages:
        score += 5
        notes.append({"sign": "+", "detail": "사업 단계 제한이 없는 공고입니다."})
    elif profile.company_stage and _contains_any(profile.company_stage, target_stages):
        score += 10
        notes.append(
            {
                "sign": "+",
                "detail": f"사업 단계({profile.company_stage})가 공고 대상 단계와 일치합니다.",
            }
        )

    if notice.eligibility.excluded_targets:
        for target in notice.eligibility.excluded_targets[:2]:
            detail = f"제외 대상 해당 여부 확인 필요: {target}"
            cautions.append(detail)
            notes.append({"sign": "-", "detail": detail})

    score = max(0.0, min(100.0, score))
    if score >= 75:
        status = "eligible"
    elif score >= 50:
        status = "needs_review"
    else:
        status = "likely_ineligible"

    # R&D 공고 실측(300건) 기준 80%가 컨소시엄/연구기관 신청구조를 갖는데,
    # 그중 "대학·출연연 전용"(기업이 아예 참여 불가)인 공고까지 매칭 후보에
    # 그대로 올라가고 있었다. 이건 감점이 아니라 확실한 하드 컷이어야 한다 —
    # 지역/규모/단계가 아무리 잘 맞아도 회사가 신청 자체를 할 수 없는
    # 공고이므로, 다른 요인과 무관하게 무조건 likely_ineligible로 강제한다.
    if notice.eligibility.applicant_structure == "컨소시엄·기관 전용(기업 참여 불가)":
        score = min(score, 20.0)
        status = "likely_ineligible"
        detail = (
            "이 공고는 대학·연구기관 전용으로 보입니다 — 기업 단독/참여 신청이"
            " 불가능할 수 있으니 원문을 확인하세요."
        )
        cautions.append(detail)
        notes.append({"sign": "-", "detail": detail})
    elif notice.eligibility.applicant_structure == "컨소시엄 필요(기업 주관/참여 가능)":
        # 사업계획서는 "이 회사가 지금 파트너를 구했는지"를 알려주지 않는다
        # (그건 신청 시점의 섭외 상황이지, 회사의 기술/업종 정보가 아니다).
        # 그래서 점수는 그대로 두되(기술 적합성 자체는 여전히 유효한 신호),
        # "파트너를 구해야 신청 가능하다"는 걸 놓치지 않도록 반드시 안내한다.
        detail = (
            "이 공고는 컨소시엄(공동 신청) 구성이 필요합니다 — 대학·연구소·"
            "타 기업 등 파트너를 먼저 구해야 신청할 수 있습니다."
        )
        cautions.append(detail)
        notes.append({"sign": "-", "detail": detail})

    return score, status, cautions, notes


def _score_notice(
    *,
    plan: NormalizedBusinessPlanSchema,
    profile: CompanyProfile,
    notice: Notice,
    normalized_notice: NormalizedNoticeSchema,
    secondary_filter_score: float | None = None,
    is_rd: bool = False,
    is_fund: bool = False,
    llm_fit_score: float | None = None,
    llm_bonus_score: float | None = None,
    llm_item_fit_score: float | None = None,
    llm_fit_count: int = 0,
    llm_bonus_count: int = 0,
    llm_item_fit_count: int = 0,
) -> MatchResult:
    use_precise_fit = is_rd or is_fund
    # R&D/자금은 가중치 재배분 이유가 서로 달라 각자 전용 프리셋을 쓴다
    # (R&D는 성장성 신호 약화, 자금은 자격요건 우선) — LLM 정밀판정 자체는 둘 다 받는다.
    weights = _RD_WEIGHTS if is_rd else (_FUND_WEIGHTS if is_fund else _DEFAULT_WEIGHTS)
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

    eligibility_score, eligibility_status, cautions, eligibility_notes = (
        _eligibility_score(profile, normalized_notice)
    )
    field_match_score, field_match = _field_match_result(plan, normalized_notice)
    base_item_fit_score = _overlap_score(plan_item_tokens, notice_item_tokens)
    item_fit_score = (base_item_fit_score * 0.70) + (field_match_score * 0.30)
    business_fit_score = _overlap_score(plan_item_tokens, notice_matching_tokens)
    growth_score = _overlap_score(plan_growth_tokens, notice_matching_tokens)
    # 가점은 "있으면 더 주는" 추가 점수라 다른 항목과 달리 근거가 없으면
    # 중립(50 근처)이 아니라 0으로 둔다 — 우대조건이 없는 공고에서 가점 받을
    # 게 없는 게 당연한 상태이지, 판단을 못 한 게 아니기 때문이다.
    bonus_score = _overlap_score(
        _tokens(plan.solution.differentiators, plan.team.capabilities),
        _tokens(normalized_notice.evaluation.preferred_conditions),
        default=0.0,
    )
    item_fit_source = "keyword"
    business_fit_source = "keyword"
    growth_source = "keyword"
    bonus_source = "keyword"
    # R&D+자금 전용: LLM이 판정한 아이템 적합도/평가기준/우대조건 점수를 반영한다.
    # 판정 문장이 적으면(_LLM_FULL_CONFIDENCE_CRITERIA_COUNT 미만) 그만큼
    # 키워드 점수를 섞어, 문장 1개짜리 판정이 0/100으로 극단적으로 튀는 걸 막는다.
    if use_precise_fit:
        item_fit_score, item_fit_used = _confidence_blend(
            llm_item_fit_score, llm_item_fit_count, item_fit_score
        )
        if item_fit_used:
            item_fit_source = "llm"
        blended_fit_score, fit_used = _confidence_blend(
            llm_fit_score, llm_fit_count, business_fit_score
        )
        if fit_used:
            business_fit_score = blended_fit_score
            business_fit_source = "llm"
            growth_score, growth_used = _confidence_blend(
                llm_fit_score, llm_fit_count, growth_score
            )
            if growth_used:
                growth_source = "llm"
        bonus_score, bonus_used = _confidence_blend(
            llm_bonus_score, llm_bonus_count, bonus_score
        )
        if bonus_used:
            bonus_source = "llm"
    # 2차 필터링 점수(secondary_filtering_service의 임베딩 유사도, 유사도
    # 상위 후보는 secondary_filtering_judge_service의 LLM 판정 점수로 대체됨)
    # 근거가 없는 공고(첨부파일 없음, 임베딩 실패, 판정 대상 요건 없음 등)는
    # 페널티 없이 중립값(_overlap_score의 default=50.0과 같은 기준)으로 채운다.
    resolved_secondary_score = (
        secondary_filter_score if secondary_filter_score is not None else 50.0
    )

    base_total_score = (
        eligibility_score * weights["eligibility"]
        + item_fit_score * weights["item_fit"]
        + business_fit_score * weights["business_fit"]
        + growth_score * weights["growth"]
    )
    # 가점은 base_total_score(0~100)에 가산만 한다 — 나머지 5개 항목만으로도
    # 100점을 채울 수 있어야 "가점 없는 공고는 만점 불가"라는 모순이 없다.
    total_score = min(100.0, base_total_score + bonus_score * _BONUS_WEIGHT)
    if eligibility_status == "likely_ineligible":
        total_score = min(total_score, 49.0)

    matched_keywords = sorted(plan_item_tokens & notice_item_tokens)[:20]

    recommendation_level = _recommendation_level(total_score)
    strengths = _strengths(
        item_fit_score=item_fit_score,
        business_fit_score=business_fit_score,
        growth_score=growth_score,
        matched_keywords=matched_keywords,
        notice=normalized_notice,
    )
    weakness = _weakness(cautions, item_fit_score, business_fit_score, normalized_notice)
    strategy = _strategy_suggestion(normalized_notice, growth_score)

    # logger.info(
    #     "🧠 AI 정밀 판정 근거 (notice_id=%s): 💪 강점=%s | ⚠️ 주의=%s | 💡 제안=%s",
    #     notice.id,
    #     strengths,
    #     weakness,
    #     strategy,
    # )

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
            # bonus는 weights 딕셔너리에 없다 — 나머지 항목과 나눠 갖는 비율이
            # 아니라 base_total_score 위에 가산되는 고정값(_BONUS_WEIGHT)이라서,
            # 화면 표시용으로만 여기 같이 담아 보낸다.
            "weights": {**weights, "bonus": _BONUS_WEIGHT},
        },
        # 각 점수가 LLM 판정(R&D+자금)에서 왔는지 키워드 겹침 fallback인지 표시.
        "score_sources": {
            "item_fit": item_fit_source,
            "business_fit": business_fit_source,
            "growth": growth_source,
            "bonus": bonus_source,
        },
        "secondary_filter_available": secondary_filter_score is not None,
        "matched_keywords": matched_keywords,
        "cautions": cautions + normalized_notice.matching.caution_points[:3],
        "eligibility_notes": eligibility_notes,
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
    notice: NormalizedNoticeSchema,
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
        signal = notice.matching.suitable_company_profile
        reason = f" 공고가 찾는 기업상({signal})과 사업계획서 내용이 겹칩니다." if signal else ""
        strengths.append(
            f"사업 정합성이 {business_fit_score:.0f}점으로 높습니다.{reason}"
        )
    if growth_score >= 65:
        criteria = notice.evaluation.criteria[:2]
        reason = (
            f" 평가기준({', '.join(criteria)})에 부합하는 성장 전략이 사업계획서에 있습니다."
            if criteria
            else ""
        )
        strengths.append(f"성장성이 {growth_score:.0f}점으로 높습니다.{reason}")
    if not strengths:
        signals = notice.matching.matching_signals[:2]
        hint = (
            f" 공고가 보는 핵심 조건({', '.join(signals)})과의 연관성을 사업계획서에"
            " 더 구체적으로 담으면 점수를 올릴 수 있습니다."
            if signals
            else ""
        )
        strengths.append(
            f"아이템 적합도 {item_fit_score:.0f}점 · 사업 정합성 {business_fit_score:.0f}점 · "
            f"성장성 {growth_score:.0f}점으로, 세 항목 모두 뚜렷한 강점 기준(65점)에는"
            f" 못 미칩니다.{hint}"
        )
    return strengths


def _weakness(
    cautions: list[str],
    item_fit_score: float,
    business_fit_score: float,
    notice: NormalizedNoticeSchema,
) -> str | None:
    weakness: list[str] = []
    weakness.extend(cautions[:3])
    if item_fit_score < 50:
        keywords = notice.matching.keywords[:3]
        hint = (
            f" 사업계획서에 {', '.join(keywords)} 관련 내용을 구체적으로 추가하세요."
            if keywords
            else " 사업 아이템과 공고 지원 분야의 연관성을 더 구체적으로 서술하세요."
        )
        weakness.append(f"아이템 적합도가 {item_fit_score:.0f}점으로 낮습니다.{hint}")
    if business_fit_score < 50:
        signals = notice.matching.matching_signals[:2]
        hint = (
            f" 공고가 요구하는 조건({', '.join(signals)})에 맞춰 사업계획서 내용을 보강하세요."
            if signals
            else " 공고의 지원 목적·평가기준에 맞춰 사업계획서 내용을 보강하세요."
        )
        weakness.append(f"사업 정합성이 {business_fit_score:.0f}점으로 낮습니다.{hint}")
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


def _rank_judge_candidates(
    secondary_result: SecondaryFilteringResult,
    fit_category_groups: list[set[int]] | None,
) -> list[int]:
    """전체 유사도 상위 _SECONDARY_FILTERING_JUDGE_TOP_K건 + R&D/자금
    카테고리 안에서만 다시 뽑은 상위 _FIT_CATEGORY_JUDGE_TOP_K건을 합친다.
    R&D/자금을 하나로 합쳐서 뽑으면 한쪽 유사도가 체계적으로 높을 때 다른
    쪽이 밀릴 수 있어 카테고리별로 따로 뽑는다."""
    scores = secondary_result.scores
    general_top = sorted(scores, key=lambda nid: scores[nid], reverse=True)[
        :_SECONDARY_FILTERING_JUDGE_TOP_K
    ]
    fit_top: list[int] = []
    for group in fit_category_groups or []:
        group_candidates = [nid for nid in scores if nid in group]
        fit_top.extend(
            sorted(group_candidates, key=lambda nid: scores[nid], reverse=True)[
                :_FIT_CATEGORY_JUDGE_TOP_K
            ]
        )
    return list(dict.fromkeys(general_top + fit_top))


async def _judge_top_candidates(
    *,
    session: AsyncSession,
    log_id: int,
    business_plan_id: int,
    plan: NormalizedBusinessPlanSchema,
    profile: CompanyProfile,
    secondary_result: SecondaryFilteringResult,
    passed: list[tuple[Notice, NormalizedNoticeSchema]],
    fit_judged_notice_ids: set[int],
    fit_category_groups: list[set[int]] | None = None,
) -> tuple[dict[int, float], dict[int, JudgedSecondaryScore]]:
    """1차 판정 대상(_rank_judge_candidates)을 뽑아 _judge_notice_ids로 판정한다."""
    ranked_notice_ids = _rank_judge_candidates(secondary_result, fit_category_groups)
    return await _judge_notice_ids(
        session=session,
        log_id=log_id,
        business_plan_id=business_plan_id,
        plan=plan,
        profile=profile,
        secondary_result=secondary_result,
        passed=passed,
        fit_judged_notice_ids=fit_judged_notice_ids,
        ranked_notice_ids=ranked_notice_ids,
    )


async def _judge_notice_ids(
    *,
    session: AsyncSession,
    log_id: int,
    business_plan_id: int,
    plan: NormalizedBusinessPlanSchema,
    profile: CompanyProfile,
    secondary_result: SecondaryFilteringResult,
    passed: list[tuple[Notice, NormalizedNoticeSchema]],
    fit_judged_notice_ids: set[int],
    ranked_notice_ids: list[int],
) -> tuple[dict[int, float], dict[int, JudgedSecondaryScore]]:
    """ranked_notice_ids로 지정된 공고만 judge_notice()로 정밀 판정한다(순위
    계산 자체는 호출자 책임 — _judge_top_candidates의 1차 판정과
    _run_matching_locked의 최종 상위권 보정 판정이 이 함수를 공유한다).

    판정 결과는 (business_plan_id, notice_id, 프로필 스냅샷) 기준으로
    secondary_filtering_judgment 테이블에 캐싱한다(2026-07-16, RAG 성능
    개선 검토 — 같은 사업계획서로 매칭을 반복 실행해도 LLM을 다시 부르지
    않기 위함). 프로필이 바뀌면 profile_fingerprint가 달라져 자동으로
    캐시 미스가 난다(profile_fingerprint 참고).

    캐시 확인/저장(session 필요)은 순차로, 실제 LLM 판정(session 없음)만
    병렬로 실행한다 — secondary_filtering_service의 임베딩 확인이 공유
    세션 대신 공고별 독립 세션(async_session_factory)을 쓰는 것과 달리,
    여기는 세션이 필요한 조회/저장을 아예 병렬 구간 밖으로 뺀다(캐시
    체크는 가벼운 단건 조회라 별도 세션을 새로 여는 비용이 더 크다고
    판단).
    """
    final_scores = dict(secondary_result.scores)
    judged_by_notice: dict[int, JudgedSecondaryScore] = {}

    if not ranked_notice_ids:
        return final_scores, judged_by_notice

    notice_by_id = {notice.id: (notice, normalized) for notice, normalized in passed}
    base_fingerprint = f"{profile_fingerprint(profile)}:no-exclusion-v1"

    def _judgment_fingerprint(notice_id: int) -> str:
        if notice_id in fit_judged_notice_ids:
            # 판정 기준(item_fit 추가, criteria_fit/item_fit 폴백 질문 추가)이
            # 바뀔 때마다 버전을 올린다 — 안 올리면 구조가 다른 옛 캐시가 재사용된다.
            return f"{base_fingerprint}:fit-v4"
        return base_fingerprint

    # 1단계(순차, session 필요): 캐시 확인.
    to_judge: list[int] = []
    for notice_id in ranked_notice_ids:
        cached = await get_cached_judgment(
            session,
            business_plan_id=business_plan_id,
            notice_id=notice_id,
            profile_fingerprint=_judgment_fingerprint(notice_id),
        )
        if cached is None:
            to_judge.append(notice_id)
            continue
        try:
            # 옛 is_exclusion 키 캐시 행은 구조가 달라 TypeError가 난다 —
            # 캐시 미스로 취급해 재판정시킨다.
            cached_judgments = [CriterionJudgment(**item) for item in cached.judgments]
        except TypeError:
            to_judge.append(notice_id)
            continue
        judged = JudgedSecondaryScore(
            score=float(cached.score),
            excluded=cached.excluded,
            fit_score=float(cached.fit_score) if cached.fit_score is not None else None,
            bonus_score=(
                float(cached.bonus_score) if cached.bonus_score is not None else None
            ),
            item_fit_score=(
                float(cached.item_fit_score)
                if cached.item_fit_score is not None
                else None
            ),
            judgments=cached_judgments,
        )
        final_scores[notice_id] = judged.score
        judged_by_notice[notice_id] = judged

    if to_judge:
        # 2단계(병렬, session 없음): 캐시 미스만 실제로 LLM 판정.
        async def _judge_one(
            notice_id: int,
        ) -> tuple[int, JudgedSecondaryScore | None]:
            _, normalized_notice = notice_by_id[notice_id]
            include_fit = notice_id in fit_judged_notice_ids
            async with _secondary_filtering_judge_semaphore:
                # criterion-aware evidence 보강(2026-07-16, RAG 성능 개선
                # 검토) — 사업계획서 유사도 기반 evidence만으로는 개별
                # 요건(지역/제외대상 등)과 무관한 근거가 섞일 수 있어, 요건
                # 문장 자체로 한 번 더 검색해 병합한다.
                criterion_statements = build_criteria_statements(
                    normalized_notice, include_fit=include_fit
                )
                criterion_evidence = await get_criterion_evidence(
                    notice_id, criterion_statements
                )
                evidence = merge_evidence(
                    secondary_result.evidence.get(notice_id, []), criterion_evidence
                )
                judged = await judge_notice(
                    profile=profile,
                    plan=plan,
                    notice=normalized_notice,
                    evidence=evidence,
                    include_fit=include_fit,
                )
            return notice_id, judged

        judged_results = await asyncio.gather(
            *(_judge_one(notice_id) for notice_id in to_judge)
        )

        # 3단계(순차, session 필요): 새로 판정한 결과만 캐시에 저장.
        for notice_id, judged in judged_results:
            if judged is None:
                continue
            final_scores[notice_id] = judged.score
            judged_by_notice[notice_id] = judged
            await save_judgment(
                session,
                business_plan_id=business_plan_id,
                notice_id=notice_id,
                profile_fingerprint=_judgment_fingerprint(notice_id),
                score=judged.score,
                excluded=judged.excluded,
                fit_score=judged.fit_score,
                bonus_score=judged.bonus_score,
                item_fit_score=judged.item_fit_score,
                judgments=[asdict(j) for j in judged.judgments],
            )

    logger.info(
        "2차 필터링 LLM 판정 [match_log_id=%s] 완료: 유사도 상위 %d건 중 판정 "
        "%d건(캐시 재사용 %d건) (나머지는 정규화 단계에서 판정 가능한 자격/"
        "제외 요건이 없어 유사도 점수를 그대로 사용)",
        log_id,
        len(ranked_notice_ids),
        len(judged_by_notice),
        len(ranked_notice_ids) - len(to_judge),
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
            "excluded": False,
            "reasons": (
                [
                    {
                        "criterion": judgment.criterion,
                        "status": judgment.status,
                        "evidence": judgment.evidence,
                        "group": judgment.group,
                        "is_exclusion": False,
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
    """매칭 파이프라인 진입점. 전체 동시 실행 개수를 세마포어로 제한해, 서로
    다른 유저의 매칭이 겹쳐 OpenAI 호출 한도를 나눠 쓰는 걸 막는다."""
    async with _matching_pipeline_semaphore:
        return await _run_matching_locked(
            session, log=log, plan=plan, profile=profile, max_results=max_results
        )


async def _run_matching_locked(
    session: AsyncSession,
    *,
    log: MatchLog,
    plan: BusinessPlan,
    profile: CompanyProfile,
    max_results: int,
) -> list[MatchResult]:
    # 매칭이 느려질 때 추측 대신 로그로 바로 어느 단계인지 짚을 수 있도록,
    # 주요 단계 경계마다 소요 시간을 재서 마지막에 한 줄로 남긴다(2026-07-16).
    stage_started_at = time.monotonic()
    stage_durations: dict[str, float] = {}

    def _mark_stage(name: str) -> None:
        nonlocal stage_started_at
        now = time.monotonic()
        stage_durations[name] = now - stage_started_at
        stage_started_at = now

    normalized_plan = _parse_business_plan(plan)
    eligibility_result = await get_eligible_notices(session, profile)
    candidates = await match_log_repository.list_normalized_notice_candidates(
        session,
        notice_ids=eligibility_result.notice_ids,
    )
    _mark_stage("1차_하드필터+후보조회")
    logger.info(
        "매칭 시작 (match_log_id=%s, business_plan_id=%s): 1차 하드필터 통과 "
        "%d건 중 정규화 완료 후보 공고 %d건 (축별 집계=%s)",
        log.id,
        plan.id,
        len(eligibility_result.notice_ids),
        len(candidates),
        eligibility_result.counts,
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

    # docs/matching-pipeline.md "로깅 요구사항" — 1차 하드필터(지역/대상/업력/
    # 기간, docs/first-filtering.md)는 위 get_eligible_notices()에서 이미
    # 끝났고, 여기서부터는 그 결과 위에 품질 필터(정규화 필수 필드 존재 여부)
    # 만 이 루프 안에서 추가로 적용한다. 어느 기준에서 몇 건이 걸러졌는지는
    # 로그로만 추적할 수 있다.
    quality_failed: dict[int, list[str]] = {}
    parse_failed_ids: list[int] = []
    quantitative_failed: dict[int, str] = {}
    eligibility_counts: dict[str, int] = {
        "eligible": 0,
        "needs_review": 0,
        "likely_ineligible": 0,
    }

    # PPT 원래 설계("2차 필터링 · 정량 적합도 평가 — 임계값 이상만 통과")를
    # 실제로 구현한 게이트. _eligibility_score(신청주체 구조·지역·기업규모·
    # 단계)를 임베딩·LLM 판정(비용이 큰 RAG·LLM 단계) 이전에 먼저 계산해,
    # likely_ineligible로 확정된 후보는 여기서 걸러낸다 — 그래야 RAG·LLM
    # 호출 자체가 줄어 PPT가 말한 비용 효율이 실현된다. 이전엔 이 점수를
    # _score_notice에서 맨 마지막에만 계산해서, 명백히 안 맞는 공고까지
    # 전부 임베딩·LLM 호출을 거친 뒤에야 낮은 점수로 걸러졌다.
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

        _, eligibility_status, _, _ = _eligibility_score(profile, normalized_notice)
        if eligibility_status == "likely_ineligible":
            quantitative_failed[notice.id] = (
                normalized_notice.eligibility.applicant_structure or "자격요건 불일치"
            )
            continue

        passed.append((notice, normalized_notice))

    _mark_stage("품질필터+정량게이트")

    if quantitative_failed:
        logger.info(
            "2차 필터링(정량 게이트) [match_log_id=%s] 자격요건 미달로 %d건 제외"
            " (RAG·LLM 단계 진입 전): %s",
            log.id,
            len(quantitative_failed),
            quantitative_failed,
        )

    if not passed:
        logger.warning(
            "매칭 불가 (match_log_id=%s): 후보 %d건 전부 품질 기준 미달·파싱 실패·"
            "자격요건 미달(정량 게이트)로 제외됨",
            log.id,
            len(candidates),
        )
        raise MatchingNotReadyError(
            "매칭 기준을 충족하는 공고가 없습니다. 공고 정규화 품질을 확인해주세요."
        )

    # R&D(기술개발) 공고는 지원자격·평가기준이 원문에 길게 나열되는 경우가
    # 많아, 2차 필터링(임베딩 유사도 검색)에서 일반 공고보다 더 넓게 훑어야
    # 자격요건 근거를 놓치지 않는다 — run_secondary_filtering에 넘길
    # notice_id 집합을 여기서 category_id로 가려낸다.
    rd_category_id = (
        await session.execute(
            select(KgCategory.id).where(KgCategory.name == CategoryName.TECH)
        )
    ).scalar_one_or_none()
    fund_category_id = (
        await session.execute(
            select(KgCategory.id).where(KgCategory.name == CategoryName.FUND)
        )
    ).scalar_one_or_none()
    rd_notice_ids = (
        {notice.id for notice, _ in passed if notice.category_id == rd_category_id}
        if rd_category_id is not None
        else set()
    )
    fund_notice_ids = (
        {notice.id for notice, _ in passed if notice.category_id == fund_category_id}
        if fund_category_id is not None
        else set()
    )
    fit_judged_notice_ids = rd_notice_ids | fund_notice_ids

    # 2차 필터링(docs/matching-pipeline.md 4단계) — 1차 하드필터
    # (get_eligible_notices) + 품질 필터 + 정량 게이트를 모두 통과한 `passed`에
    # 한해서만 공고 PDF 임베딩·유사도 검색을 수행한다(전체 후보를 다 임베딩하면
    # 비용이 크므로, 명백히 무관하거나 자격 미달인 공고를 먼저 제거하는 것과
    # 같은 이유). 임베딩이 없거나 실패한 공고는 결과에서 빠지고 _score_notice가
    # 중립값으로 처리한다.
    secondary_result = await run_secondary_filtering(
        session,
        business_plan_id=plan.id,
        candidate_notice_ids=[notice.id for notice, _ in passed],
        rd_notice_ids=fit_judged_notice_ids,
    )
    _mark_stage("2차필터링(임베딩+유사도검색)")
    # 유사도 상위 K건만 LLM으로 정밀 판정한다(docs/secondary-filtering-llm-judge-guide.md)
    # — final_scores는 판정된 공고는 판정 점수, 나머지는 기존 유사도 점수를 담는다.
    final_secondary_scores, secondary_judgments = await _judge_top_candidates(
        session=session,
        log_id=log.id,
        business_plan_id=plan.id,
        plan=normalized_plan,
        profile=profile,
        secondary_result=secondary_result,
        passed=passed,
        fit_judged_notice_ids=fit_judged_notice_ids,
        fit_category_groups=[rd_notice_ids, fund_notice_ids],
    )
    _mark_stage("LLM_정밀판정")

    scored: list[ScoredNotice] = []
    for notice, normalized_notice in passed:
        judged = secondary_judgments.get(notice.id)
        result = _score_notice(
            plan=normalized_plan,
            profile=profile,
            notice=notice,
            normalized_notice=normalized_notice,
            secondary_filter_score=final_secondary_scores.get(notice.id),
            is_rd=notice.id in rd_notice_ids,
            is_fund=notice.id in fund_notice_ids,
            llm_fit_score=judged.fit_score if judged else None,
            llm_bonus_score=judged.bonus_score if judged else None,
            llm_item_fit_score=judged.item_fit_score if judged else None,
            llm_fit_count=_group_judgment_count(judged, "criteria_fit"),
            llm_bonus_count=_group_judgment_count(judged, "bonus_fit"),
            llm_item_fit_count=_group_judgment_count(judged, "item_fit"),
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
    _mark_stage("점수산출")

    scored.sort(key=lambda item: item.result.total_score or Decimal("0"), reverse=True)

    # 최종 보정: 1차 판정(유사도 top-K)에 못 든 R&D/자금 공고가 키워드 폴백
    # 점수만으로 종합점수 상위 _FINAL_RERANK_JUDGE_TOP_N위 안에 들면, 그
    # 공고만 다시 LLM으로 판정해 점수를 실제 근거 기반으로 갱신한다.
    rerun_ids = [
        item.notice.id
        for item in scored[:_FINAL_RERANK_JUDGE_TOP_N]
        if item.notice.id in fit_judged_notice_ids
        and item.notice.id not in secondary_judgments
    ]
    if rerun_ids:
        rerun_scores, rerun_judgments = await _judge_notice_ids(
            session=session,
            log_id=log.id,
            business_plan_id=plan.id,
            plan=normalized_plan,
            profile=profile,
            secondary_result=secondary_result,
            passed=passed,
            fit_judged_notice_ids=fit_judged_notice_ids,
            ranked_notice_ids=rerun_ids,
        )
        final_secondary_scores.update(rerun_scores)
        secondary_judgments.update(rerun_judgments)

        passed_by_id = {notice.id: (notice, nn) for notice, nn in passed}
        scored_by_id = {item.notice.id: index for index, item in enumerate(scored)}
        for notice_id in rerun_ids:
            judged = secondary_judgments.get(notice_id)
            notice, normalized_notice = passed_by_id[notice_id]
            result = _score_notice(
                plan=normalized_plan,
                profile=profile,
                notice=notice,
                normalized_notice=normalized_notice,
                secondary_filter_score=final_secondary_scores.get(notice_id),
                is_rd=notice_id in rd_notice_ids,
                is_fund=notice_id in fund_notice_ids,
                llm_fit_score=judged.fit_score if judged else None,
                llm_bonus_score=judged.bonus_score if judged else None,
                llm_item_fit_score=judged.item_fit_score if judged else None,
            )
            result.recommendation_run_id = log.id
            scored[scored_by_id[notice_id]] = ScoredNotice(notice=notice, result=result)
        scored.sort(key=lambda item: item.result.total_score or Decimal("0"), reverse=True)
        logger.info(
            "최종 보정 [match_log_id=%s]: 종합점수 상위 %d위 안에 든 미판정 R&D/"
            "자금 공고 %d건 재판정 완료 (notice_id=%s)",
            log.id,
            _FINAL_RERANK_JUDGE_TOP_N,
            len(rerun_ids),
            rerun_ids,
        )
    _mark_stage("최종보정_재판정")

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
    _mark_stage("결과저장")

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
    logger.info(
        "매칭 단계별 소요시간 (match_log_id=%s, 총 %.1f초): %s",
        log.id,
        sum(stage_durations.values()),
        {name: round(seconds, 2) for name, seconds in stage_durations.items()},
    )
    return selected

"""
services/secondary_filtering_judge_service.py

2차 필터링(docs/matching-pipeline.md 4단계)의 LLM 판정·집계 부분
(docs/secondary-filtering-llm-judge-guide.md 설계 문서 참고). bizSupportNavigator의
services/llm_judge.py + services/score_aggregate.py 패턴을 이식한다: 정규화된
공고의 자격/제외 요건을 문장 단위로 만들고, 회사 프로필 + 2차 필터링
(secondary_filtering_service)이 찾은 근거 청크를 근거로 LLM이 각 문장을
충족/미충족/정보부족으로 판정하게 한 뒤, 자격 70% + 제외 30% 가중 평균으로
하나의 점수로 합친다.

제외요건이 "미충족"(=제외 대상에 해당함)으로 확정되면 점수를 낮은 값으로
캡한다 — bizSupportNavigator는 이 경우 0으로 완전히 캡하지만, 이 저장소는
이미 matching_service._eligibility_score의 likely_ineligible 캡(총점 49점
이하)이 있어 이중 안전장치로 삼기 위해 0이 아니라 _EXCLUDED_SCORE_CAP을 쓴다.

2026-07-16(적합도 판정 확장, R&D 전용): 평가기준·우대조건도 같은 LLM 호출로
판정해 criteria_fit/bonus_fit 그룹으로 추가하고, 별도 fit_score/bonus_score로 집계한다.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Literal

from app.ai.secondary_filtering_judge_client import AiJudgeError, judge_criteria
from app.models.company import CompanyProfile
from app.schemas.business_plan import NormalizedBusinessPlanSchema
from app.schemas.notice_normalization import NormalizedNoticeSchema
from app.services.secondary_filtering_service import EvidenceChunk

logger = logging.getLogger(__name__)

CriterionStatus = Literal["충족", "미충족", "정보부족"]
CriterionGroup = Literal[
    "eligibility", "exclusion", "criteria_fit", "bonus_fit", "item_fit"
]
"""eligibility/exclusion은 자격요건 축. criteria_fit/bonus_fit/item_fit은
적합도 축(R&D+자금 전용)."""

_STATUS_WEIGHT: dict[CriterionStatus, float] = {
    "충족": 1.0,
    "정보부족": 0.5,
    "미충족": 0.0,
}
_ELIGIBILITY_WEIGHT = 0.7
_EXCLUSION_WEIGHT = 0.3
NEUTRAL_SCORE = 50.0
"""판정 대상 요건이 없을 때(정규화 단계에서 eligibility/제외요건을 전혀 못
뽑은 공고)의 중립값. matching_service._score_notice의 secondary_filter_score
중립값(50.0)과 통일해, "근거 없음"이 점수에 유불리를 주지 않게 한다."""


@dataclass(frozen=True)
class CriterionJudgment:
    criterion: str
    status: CriterionStatus
    evidence: str | None
    group: CriterionGroup


@dataclass(frozen=True)
class JudgedSecondaryScore:
    score: float
    excluded: bool
    """제외요건 확정으로 _EXCLUDED_SCORE_CAP이 적용됐는지."""
    fit_score: float | None = None
    """criteria_fit 그룹(평가기준) 판정의 단순 평균*100. 판정 대상 문장이 없으면
    None — matching_service가 이 경우 기존 키워드 겹침 점수를 그대로 쓴다."""
    bonus_score: float | None = None
    """bonus_fit 그룹(우대조건) 판정의 단순 평균*100. 의미는 fit_score와 동일."""
    item_fit_score: float | None = None
    """item_fit 그룹(사업 아이템·업종 부합) 판정의 단순 평균*100. fit_score와 동일한 의미."""
    judgments: list[CriterionJudgment] = field(default_factory=list)


# 사업계획서·기업 프로필 어디에도 안 나오고, 세무서·신용평가사 실시간 조회
# 없이는 사업계획서 텍스트만으로 절대 판단할 수 없는 제외요건 키워드. 이런
# 항목은 어떤 공고에서도 100% "정보부족"으로 귀결되거나(실측, 2026-07-15
# 스크린샷 — "재무 요건 불충족", "신용유의정보", "자본잠식" 전부 정보부족)
# LLM이 근거 없이 낙관적으로 "충족"을 찍는 식으로만 답이 나온다 — 어느 쪽이든
# 실제 매칭 품질 신호가 아니라 모든 공고에 똑같이 끼는 잡음이라, 판정 대상
# 문장 자체를 만들지 않고 애초에 제외한다.
_UNVERIFIABLE_KEYWORDS = (
    "신용",
    "재무",
    "자본잠식",
    "체납",
    "부채비율",
    "재무제표",
    "결산",
)


def _is_unverifiable_from_business_plan(statement: str) -> bool:
    return any(keyword in statement for keyword in _UNVERIFIABLE_KEYWORDS)


def _build_criteria(
    notice: NormalizedNoticeSchema,
    *,
    include_fit: bool = False,
) -> list[tuple[str, str, CriterionGroup]]:
    """(criterion_id, statement, group) 목록을 만든다.

    eligibility 쪽(지역/기업규모/업력단계/필수상태)은 정규화 단계에서 실제로
    뽑힌 필드만 문장화한다 — 애초에 못 뽑은 필드까지 "정보부족" 판정으로
    채우면 신호만 희석된다. exclusion 쪽(제외대상, 실격사유)은
    bizSupportNavigator llm_judge.py 관례와 동일하게 "~에 해당하지 않음"으로
    긍정 재구성해, 충족/미충족의 의미(둘 다 "이 기업에 좋음"이 충족)를
    eligibility와 통일한다. 신용·재무 상태처럼 사업계획서로 원천적으로
    검증 불가능한 문장은 같은 이유(신호 희석 방지)로 아예 만들지 않는다.

    include_fit=True일 때만 criteria_fit/bonus_fit(평가기준·우대조건 판정,
    현재 R&D 공고 전용)을 덧붙인다.
    """
    items: list[tuple[str, str, CriterionGroup]] = []
    eligibility = notice.eligibility

    if eligibility.target_regions:
        items.append(
            (
                "elig:region",
                f"사업장 지역이 다음 중 하나에 해당함: {', '.join(eligibility.target_regions)}",
                "eligibility",
            )
        )
    if eligibility.target_company_size:
        items.append(
            (
                "elig:size",
                f"기업 규모가 다음 중 하나에 해당함: {', '.join(eligibility.target_company_size)}",
                "eligibility",
            )
        )
    if eligibility.target_business_stage:
        items.append(
            (
                "elig:stage",
                f"업력/사업 단계가 다음 중 하나에 해당함: {', '.join(eligibility.target_business_stage)}",
                "eligibility",
            )
        )
    if eligibility.required_status:
        items.append(
            (
                "elig:status",
                f"다음 요건을 충족함: {', '.join(eligibility.required_status)}",
                "eligibility",
            )
        )

    for index, target in enumerate(()):
        if _is_unverifiable_from_business_plan(target):
            continue
        items.append((f"excl:target:{index}", f"{target}에 해당하지 않음", "exclusion"))
    for index, reason in enumerate(()):
        if _is_unverifiable_from_business_plan(reason):
            continue
        items.append((f"excl:reason:{index}", f"{reason}에 해당하지 않음", "exclusion"))

    if include_fit:
        if eligibility.target_industries:
            for index, industry in enumerate(eligibility.target_industries):
                items.append(
                    (
                        f"fit:item:{index}",
                        f"사업 아이템(업종·기술·제품)이 다음 지원 대상 업종/분야에 해당함: {industry}",
                        "item_fit",
                    )
                )
        else:
            # 원문에 "지원 대상 업종" 항목이 없는 공고도 아이템 적합도를
            # 키워드 겹침으로만 두지 않도록, 공고의 분야·지원유형·매칭
            # 키워드로 일반형 문장을 만든다.
            item_signals = [
                value
                for value in (
                    notice.basic.category,
                    *notice.support.support_type,
                    *notice.matching.keywords,
                )
                if value
            ]
            if item_signals:
                items.append(
                    (
                        "fit:item:fallback",
                        "사업 아이템(업종·기술·제품)이 공고의 지원 분야/유형에 해당함: "
                        f"{', '.join(item_signals[:5])}",
                        "item_fit",
                    )
                )
        if notice.evaluation.criteria:
            for index, criterion in enumerate(notice.evaluation.criteria):
                items.append(
                    (
                        f"fit:criteria:{index}",
                        f"다음 평가기준에 부합하는 근거가 있음: {criterion}",
                        "criteria_fit",
                    )
                )
        else:
            # 원문에 "평가기준" 섹션이 없는 공고도 사업 정합성/성장성을 키워드
            # 겹침으로만 두지 않도록, 공고의 매칭 시그널로 일반형 문장을 만든다.
            signals = notice.matching.matching_signals or (
                [notice.matching.suitable_company_profile]
                if notice.matching.suitable_company_profile
                else []
            )
            if signals:
                items.append(
                    (
                        "fit:criteria:fallback",
                        "사업계획서 내용이 공고의 지원 목적·매칭 조건에 부합함: "
                        f"{', '.join(signals[:5])}",
                        "criteria_fit",
                    )
                )
        for index, condition in enumerate(notice.evaluation.preferred_conditions):
            items.append(
                (
                    f"fit:bonus:{index}",
                    f"다음 우대조건에 해당함: {condition}",
                    "bonus_fit",
                )
            )

    return items


def build_criteria_statements(
    notice: NormalizedNoticeSchema, *, include_fit: bool = False
) -> list[str]:
    """_build_criteria(notice)의 문장 부분만 뽑아 공개한다(2026-07-16, RAG
    성능 개선 검토). matching_service._judge_top_candidates가 LLM 판정 전에
    이 문장들을 그대로 임베딩해 secondary_filtering_service.get_criterion_evidence로
    criterion-aware evidence를 보강하는 데 쓴다 — judge_notice() 내부의
    _build_criteria 호출과 별개로 한 번 더 계산되지만, 순수 함수라 비용은
    없다(실제 비용은 이 문장들을 임베딩하는 embed_texts 호출 쪽에서 발생)."""
    return [
        statement
        for _, statement, _ in _build_criteria(notice, include_fit=include_fit)
    ]


def profile_fingerprint(profile: CompanyProfile) -> str:
    """LLM 판정 캐시 키에 넣을 프로필 스냅샷 해시(2026-07-16, RAG 성능 개선
    검토). _company_profile_text가 참조하는 프로필 필드만 그대로 반영한다
    (사업계획서 쪽 필드는 business_plan_id가 이미 캐시 키에 있어 여기 넣지
    않는다) — 사용자가 이 필드 중 하나라도 바꾸면 해시가 달라져 캐시가
    자동으로 무효화된다. 공고 재수집으로 normalized_json이 바뀌는 경우까지는
    다루지 않는다(SecondaryFilteringJudgment 모델 docstring 참고, TBD)."""
    raw = "|".join(
        str(value)
        for value in (
            profile.company_size,
            profile.business_type,
            profile.region_name,
            profile.industry_code,
            profile.company_stage,
            profile.business_years,
            profile.employee_count,
            profile.annual_revenue,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _company_profile_text(
    profile: CompanyProfile, plan: NormalizedBusinessPlanSchema
) -> str:
    company_size_line = f"기업규모: {profile.company_size or '정보없음'}"
    if profile.company_size == "중소기업":
        # "중소기업"은 소상공인/소기업/중기업 세분값을 포괄하는 상위 개념임을
        # LLM에 명시해, 세분 불일치로 오판하지 않게 한다.
        company_size_line += (
            " (소상공인·소기업·중기업을 모두 포괄하는 상위 분류이며,"
            " 상시근로자 수 등 세부 구분 정보는 없음)"
        )
    return (
        f"{company_size_line}\n"
        f"사업자유형: {profile.business_type or '정보없음'}\n"
        f"지역: {profile.region_name or '정보없음'}\n"
        f"업종코드: {profile.industry_code or '정보없음'}\n"
        f"사업 단계: {profile.company_stage or '정보없음'}\n"
        f"업력(년): {profile.business_years if profile.business_years is not None else '정보없음'}\n"
        f"상시근로자 수: {profile.employee_count if profile.employee_count is not None else '정보없음'}\n"
        f"연매출(원): {profile.annual_revenue if profile.annual_revenue is not None else '정보없음'}\n"
        f"업종: {plan.company.industry or '정보없음'}\n"
        f"사업계획 요약: {plan.solution.summary or '정보없음'}"
    )


def _fallback_judgments(
    items: list[tuple[str, str, CriterionGroup]],
) -> list[CriterionJudgment]:
    return [
        CriterionJudgment(
            criterion=statement, status="정보부족", evidence=None, group=group
        )
        for _, statement, group in items
    ]


def _group_average(judgments: list[CriterionJudgment]) -> float | None:
    if not judgments:
        return None
    return sum(_STATUS_WEIGHT[j.status] for j in judgments) / len(judgments)


def _group_avg_score(
    judgments: list[CriterionJudgment], group: CriterionGroup
) -> float | None:
    """judgments 중 group에 속한 것만 골라 단순 평균*100을 낸다. 판정 대상이
    없으면 None(중립 50점과 구분 — matching_service가 이때만 키워드 겹침을 유지)."""
    matched = [j for j in judgments if j.group == group]
    avg = _group_average(matched)
    return round(avg * 100, 2) if avg is not None else None


def aggregate_secondary_score(
    judgments: list[CriterionJudgment],
) -> JudgedSecondaryScore:
    """판정 결과를 집계한다. 자격요건 축(score)은 자격 70%+제외 30% 가중평균,
    제외요건 미충족 확정 시 _EXCLUDED_SCORE_CAP으로 캡한다. 적합도 축
    (fit_score/bonus_score)은 별도 필드로 반환하고 score 계산에는 안 섞는다."""
    if not judgments:
        return JudgedSecondaryScore(score=NEUTRAL_SCORE, excluded=False, judgments=[])

    eligibility = [j for j in judgments if j.group == "eligibility"]
    eligibility_avg = _group_average(eligibility)
    if eligibility_avg is None:
        raw_score = NEUTRAL_SCORE
    else:
        raw_score = eligibility_avg * 100
    return JudgedSecondaryScore(
        score=round(raw_score, 2),
        excluded=False,
        fit_score=_group_avg_score(judgments, "criteria_fit"),
        bonus_score=_group_avg_score(judgments, "bonus_fit"),
        item_fit_score=_group_avg_score(judgments, "item_fit"),
        judgments=judgments,
    )


async def judge_notice(
    *,
    profile: CompanyProfile,
    plan: NormalizedBusinessPlanSchema,
    notice: NormalizedNoticeSchema,
    evidence: list[EvidenceChunk],
    include_fit: bool = False,
) -> JudgedSecondaryScore | None:
    """공고 하나의 2차 필터링 LLM 판정 결과를 반환한다. include_fit=True면
    criteria_fit/bonus_fit(평가기준·우대조건, 현재 R&D 전용)도 같이 판정한다.

    정규화 단계에서 eligibility/제외요건을 하나도 못 뽑은 공고는 판정 대상
    문장 자체가 없으므로 None을 반환한다 — 호출자(matching_service)가 기존
    유사도 점수를 그대로 쓰도록.

    LLM 호출이 재시도 끝에도 실패하면 예외를 던지지 않고 전부 "정보부족"
    판정으로 집계한다 — 공고 하나의 LLM 실패로 전체 매칭이 중단되면 안 되고,
    "정보부족"이 이미 그 취지(판정 불가)를 정확히 표현하기 때문이다.
    """
    items = _build_criteria(notice, include_fit=include_fit)
    if not items:
        return None

    criteria = [(cid, statement) for cid, statement, _ in items]
    evidence_texts = [chunk.content for chunk in evidence]
    company_text = _company_profile_text(profile, plan)

    try:
        judged_by_id = await judge_criteria(
            company_profile_text=company_text,
            criteria=criteria,
            evidence_texts=evidence_texts,
        )
    except AiJudgeError:
        logger.warning(
            "2차 필터링 LLM 판정 실패 (notice title=%s) — 전부 정보부족으로 처리",
            notice.basic.title,
        )
        return aggregate_secondary_score(_fallback_judgments(items))

    judgments: list[CriterionJudgment] = []
    for criterion_id, statement, group in items:
        judged = judged_by_id.get(criterion_id)
        if judged is None:
            judgments.append(
                CriterionJudgment(
                    criterion=statement,
                    status="정보부족",
                    evidence=None,
                    group=group,
                )
            )
            continue
        status, evidence_text = judged
        judgments.append(
            CriterionJudgment(
                criterion=statement,
                status=status,
                evidence=evidence_text,
                group=group,
            )
        )

    return aggregate_secondary_score(judgments)

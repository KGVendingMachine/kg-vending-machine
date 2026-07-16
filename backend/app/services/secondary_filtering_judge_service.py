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

_STATUS_WEIGHT: dict[CriterionStatus, float] = {
    "충족": 1.0,
    "정보부족": 0.5,
    "미충족": 0.0,
}
_ELIGIBILITY_WEIGHT = 0.7
_EXCLUSION_WEIGHT = 0.3
_EXCLUDED_SCORE_CAP = 5.0
NEUTRAL_SCORE = 50.0
"""판정 대상 요건이 없을 때(정규화 단계에서 eligibility/제외요건을 전혀 못
뽑은 공고)의 중립값. matching_service._score_notice의 secondary_filter_score
중립값(50.0)과 통일해, "근거 없음"이 점수에 유불리를 주지 않게 한다."""


@dataclass(frozen=True)
class CriterionJudgment:
    criterion: str
    status: CriterionStatus
    evidence: str | None
    is_exclusion: bool


@dataclass(frozen=True)
class JudgedSecondaryScore:
    score: float
    excluded: bool
    """제외요건 확정으로 _EXCLUDED_SCORE_CAP이 적용됐는지."""
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


def _build_criteria(notice: NormalizedNoticeSchema) -> list[tuple[str, str, bool]]:
    """(criterion_id, statement, is_exclusion) 목록을 만든다.

    eligibility 쪽(지역/기업규모/업력단계/필수상태)은 정규화 단계에서 실제로
    뽑힌 필드만 문장화한다 — 애초에 못 뽑은 필드까지 "정보부족" 판정으로
    채우면 신호만 희석된다. exclusion 쪽(제외대상, 실격사유)은
    bizSupportNavigator llm_judge.py 관례와 동일하게 "~에 해당하지 않음"으로
    긍정 재구성해, 충족/미충족의 의미(둘 다 "이 기업에 좋음"이 충족)를
    eligibility와 통일한다. 신용·재무 상태처럼 사업계획서로 원천적으로
    검증 불가능한 문장은 같은 이유(신호 희석 방지)로 아예 만들지 않는다.
    """
    items: list[tuple[str, str, bool]] = []
    eligibility = notice.eligibility

    if eligibility.target_regions:
        items.append(
            (
                "elig:region",
                f"사업장 지역이 다음 중 하나에 해당함: {', '.join(eligibility.target_regions)}",
                False,
            )
        )
    if eligibility.target_company_size:
        items.append(
            (
                "elig:size",
                f"기업 규모가 다음 중 하나에 해당함: {', '.join(eligibility.target_company_size)}",
                False,
            )
        )
    if eligibility.target_business_stage:
        items.append(
            (
                "elig:stage",
                f"업력/사업 단계가 다음 중 하나에 해당함: {', '.join(eligibility.target_business_stage)}",
                False,
            )
        )
    if eligibility.required_status:
        items.append(
            (
                "elig:status",
                f"다음 요건을 충족함: {', '.join(eligibility.required_status)}",
                False,
            )
        )

    for index, target in enumerate(eligibility.excluded_targets):
        if _is_unverifiable_from_business_plan(target):
            continue
        items.append((f"excl:target:{index}", f"{target}에 해당하지 않음", True))
    for index, reason in enumerate(notice.evaluation.disqualification_reasons):
        if _is_unverifiable_from_business_plan(reason):
            continue
        items.append((f"excl:reason:{index}", f"{reason}에 해당하지 않음", True))

    return items


def build_criteria_statements(notice: NormalizedNoticeSchema) -> list[str]:
    """_build_criteria(notice)의 문장 부분만 뽑아 공개한다(2026-07-16, RAG
    성능 개선 검토). matching_service._judge_top_candidates가 LLM 판정 전에
    이 문장들을 그대로 임베딩해 secondary_filtering_service.get_criterion_evidence로
    criterion-aware evidence를 보강하는 데 쓴다 — judge_notice() 내부의
    _build_criteria 호출과 별개로 한 번 더 계산되지만, 순수 함수라 비용은
    없다(실제 비용은 이 문장들을 임베딩하는 embed_texts 호출 쪽에서 발생)."""
    return [statement for _, statement, _ in _build_criteria(notice)]


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
    return (
        f"기업규모: {profile.company_size or '정보없음'}\n"
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
    items: list[tuple[str, str, bool]],
) -> list[CriterionJudgment]:
    return [
        CriterionJudgment(
            criterion=statement, status="정보부족", evidence=None, is_exclusion=is_excl
        )
        for _, statement, is_excl in items
    ]


def _group_average(judgments: list[CriterionJudgment]) -> float | None:
    if not judgments:
        return None
    return sum(_STATUS_WEIGHT[j.status] for j in judgments) / len(judgments)


def aggregate_secondary_score(
    judgments: list[CriterionJudgment],
) -> JudgedSecondaryScore:
    """판정 결과를 자격 70% + 제외 30% 가중 평균으로 합친다
    (bizSupportNavigator score_aggregate.py 그대로). 한쪽 그룹이 비어 있으면
    있는 쪽만 100% 반영한다. 제외요건 중 하나라도 "미충족"(=제외 대상에
    해당함)으로 확정되면 점수를 _EXCLUDED_SCORE_CAP으로 캡한다.
    """
    if not judgments:
        return JudgedSecondaryScore(score=NEUTRAL_SCORE, excluded=False, judgments=[])

    eligibility = [j for j in judgments if not j.is_exclusion]
    exclusion = [j for j in judgments if j.is_exclusion]
    excluded = any(j.status == "미충족" for j in exclusion)

    eligibility_avg = _group_average(eligibility)
    exclusion_avg = _group_average(exclusion)
    if eligibility_avg is None:
        raw_score = exclusion_avg * 100 if exclusion_avg is not None else NEUTRAL_SCORE
    elif exclusion_avg is None:
        raw_score = eligibility_avg * 100
    else:
        raw_score = (
            eligibility_avg * _ELIGIBILITY_WEIGHT + exclusion_avg * _EXCLUSION_WEIGHT
        ) * 100

    score = min(raw_score, _EXCLUDED_SCORE_CAP) if excluded else raw_score
    return JudgedSecondaryScore(
        score=round(score, 2), excluded=excluded, judgments=judgments
    )


async def judge_notice(
    *,
    profile: CompanyProfile,
    plan: NormalizedBusinessPlanSchema,
    notice: NormalizedNoticeSchema,
    evidence: list[EvidenceChunk],
) -> JudgedSecondaryScore | None:
    """공고 하나의 2차 필터링 LLM 판정 결과를 반환한다.

    정규화 단계에서 eligibility/제외요건을 하나도 못 뽑은 공고는 판정 대상
    문장 자체가 없으므로 None을 반환한다 — 호출자(matching_service)가 기존
    유사도 점수를 그대로 쓰도록.

    LLM 호출이 재시도 끝에도 실패하면 예외를 던지지 않고 전부 "정보부족"
    판정으로 집계한다 — 공고 하나의 LLM 실패로 전체 매칭이 중단되면 안 되고,
    "정보부족"이 이미 그 취지(판정 불가)를 정확히 표현하기 때문이다.
    """
    items = _build_criteria(notice)
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
    for criterion_id, statement, is_excl in items:
        judged = judged_by_id.get(criterion_id)
        if judged is None:
            judgments.append(
                CriterionJudgment(
                    criterion=statement,
                    status="정보부족",
                    evidence=None,
                    is_exclusion=is_excl,
                )
            )
            continue
        status, evidence_text = judged
        judgments.append(
            CriterionJudgment(
                criterion=statement,
                status=status,
                evidence=evidence_text,
                is_exclusion=is_excl,
            )
        )

    return aggregate_secondary_score(judgments)

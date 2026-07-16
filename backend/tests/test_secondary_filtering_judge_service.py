"""
tests/test_secondary_filtering_judge_service.py

app/services/secondary_filtering_judge_service.py 테스트.
docs/secondary-filtering-llm-judge-guide.md 설계의 핵심(70/30 가중 집계,
제외요건 확정 시 캡, criteria 문장 생성)을 순수 함수 단위로 검증하고,
judge_notice의 LLM 호출은 monkeypatch로 대체한다(tests/test_ai_normalizer.py와
동일하게 실제 OpenAI API는 호출하지 않음).
"""

import pytest

from app.models.company import CompanyProfile
from app.schemas.business_plan import NormalizedBusinessPlanSchema
from app.schemas.notice_normalization import NormalizedNoticeSchema
from app.services import secondary_filtering_judge_service as judge_service
from app.services.secondary_filtering_judge_service import (
    NEUTRAL_SCORE,
    CriterionJudgment,
    _build_criteria,
    _company_profile_text,
    aggregate_secondary_score,
    build_criteria_statements,
    judge_notice,
    profile_fingerprint,
)

pytestmark = pytest.mark.anyio


def _notice(**eligibility_overrides) -> NormalizedNoticeSchema:
    return NormalizedNoticeSchema.model_validate(
        {
            "eligibility": {
                "target_regions": ["서울", "경기"],
                "target_company_size": ["소기업"],
                **eligibility_overrides,
            },
            "evaluation": {"disqualification_reasons": ["휴업 중인 기업"]},
        }
    )


def _plan() -> NormalizedBusinessPlanSchema:
    return NormalizedBusinessPlanSchema.model_validate(
        {"solution": {"summary": "AI 비전 검사 솔루션"}}
    )


def test_build_criteria_only_includes_present_eligibility_fields():
    notice = NormalizedNoticeSchema.model_validate(
        {"eligibility": {"target_regions": ["서울"]}}
    )

    items = _build_criteria(notice)

    ids = [item[0] for item in items]
    assert "elig:region" in ids
    assert "elig:size" not in ids  # target_company_size가 비어 있음
    assert all(group == "eligibility" for _, _, group in items)


def test_build_criteria_reframes_exclusion_positively():
    notice = _notice()

    items = _build_criteria(notice)
    exclusion_items = [item for item in items if item[2] == "exclusion"]

    assert len(exclusion_items) == 1
    assert exclusion_items[0][1] == "휴업 중인 기업에 해당하지 않음"


def test_build_criteria_omits_fit_groups_by_default():
    notice = NormalizedNoticeSchema.model_validate(
        {
            "eligibility": {"target_regions": ["서울"]},
            "evaluation": {
                "criteria": ["기술 혁신성"],
                "preferred_conditions": ["여성기업 우대"],
            },
        }
    )

    items = _build_criteria(notice)

    assert all(group not in ("criteria_fit", "bonus_fit") for _, _, group in items)


def test_build_criteria_includes_fit_groups_when_requested():
    notice = NormalizedNoticeSchema.model_validate(
        {
            "evaluation": {
                "criteria": ["기술 혁신성"],
                "preferred_conditions": ["여성기업 우대"],
            },
        }
    )

    items = _build_criteria(notice, include_fit=True)
    groups = [group for _, _, group in items]

    assert "criteria_fit" in groups
    assert "bonus_fit" in groups


def test_build_criteria_excludes_financially_unverifiable_items():
    # 사업계획서로 원천적으로 검증 불가능한 재무/신용 관련 제외요건은 판정
    # 대상 문장 자체를 안 만든다 — 어느 공고에서도 100% 정보부족으로만
    # 귀결돼 신호 없이 점수만 희석시키기 때문(실측, 2026-07-15).
    notice = NormalizedNoticeSchema.model_validate(
        {
            "eligibility": {
                "target_regions": ["서울"],
                "excluded_targets": [
                    "최근 1년 신용유의정보가 있는 기업",
                    "최근회계연도 전액 자본잠식 기업",
                    "국세·지방세 체납 기업",
                    "휴업 중인 기업",
                ],
            },
        }
    )

    items = _build_criteria(notice)
    exclusion_statements = [item[1] for item in items if item[2] == "exclusion"]

    assert exclusion_statements == ["휴업 중인 기업에 해당하지 않음"]


def test_company_profile_text_includes_business_type():
    # business_type(사업자유형)이 빠져 있으면, 프론트에서 사용자가 채워도
    # LLM 판정에 절대 반영이 안 된다(실측, 2026-07-15) — 반드시 포함돼야 함.
    profile = CompanyProfile(
        company_size="소기업", business_type="법인사업자", region_name="서울"
    )

    text = _company_profile_text(profile, _plan())

    assert "법인사업자" in text


def test_build_criteria_statements_matches_build_criteria_sentences():
    """criterion-aware evidence(2026-07-16)가 임베딩할 문장 목록이
    judge_notice가 실제로 판정하는 요건 문장과 정확히 같아야 한다."""
    notice = _notice()

    statements = build_criteria_statements(notice)
    expected = [statement for _, statement, _ in _build_criteria(notice)]

    assert statements == expected


def test_profile_fingerprint_changes_when_relevant_field_changes():
    base = CompanyProfile(company_size="소기업", region_name="서울")
    changed = CompanyProfile(company_size="중기업", region_name="서울")

    assert profile_fingerprint(base) != profile_fingerprint(changed)


def test_profile_fingerprint_changes_when_business_type_changes():
    base = CompanyProfile(company_size="소기업", business_type="법인사업자")
    changed = CompanyProfile(company_size="소기업", business_type="개인사업자")

    assert profile_fingerprint(base) != profile_fingerprint(changed)


def test_profile_fingerprint_is_stable_for_same_values():
    a = CompanyProfile(company_size="소기업", region_name="서울")
    b = CompanyProfile(company_size="소기업", region_name="서울")

    assert profile_fingerprint(a) == profile_fingerprint(b)


def test_aggregate_secondary_score_returns_neutral_when_no_judgments():
    result = aggregate_secondary_score([])

    assert result.score == NEUTRAL_SCORE
    assert result.excluded is False


def test_aggregate_secondary_score_weights_eligibility_more_than_exclusion():
    # 자격요건 전부 미충족(도메인상 부적격) + 제외요건 전부 충족(제외 대상
    # 아님)인 경우, 70/30 가중이 없으면 잘못 높게 나온다(score_aggregate.py
    # 모듈 docstring에 적힌 실측 버그와 동일한 시나리오).
    judgments = [
        CriterionJudgment(
            criterion="자격1", status="미충족", evidence=None, group="eligibility"
        ),
        CriterionJudgment(
            criterion="자격2", status="미충족", evidence=None, group="eligibility"
        ),
    ] + [
        CriterionJudgment(
            criterion=f"제외{i}", status="충족", evidence=None, group="exclusion"
        )
        for i in range(9)
    ]

    result = aggregate_secondary_score(judgments)

    # eligibility_avg=0.0*0.7 + exclusion_avg=1.0*0.3 = 30.0
    assert result.score == pytest.approx(30.0)
    assert result.excluded is False


def test_aggregate_secondary_score_caps_when_exclusion_confirmed():
    judgments = [
        CriterionJudgment(
            criterion="자격1", status="충족", evidence=None, group="eligibility"
        ),
        CriterionJudgment(
            criterion="제외1에 해당하지 않음",
            status="미충족",
            evidence="제외 대상 확인됨",
            group="exclusion",
        ),
    ]

    result = aggregate_secondary_score(judgments)

    assert result.excluded is True
    assert result.score <= judge_service._EXCLUDED_SCORE_CAP


def test_aggregate_secondary_score_computes_fit_and_bonus_separately():
    judgments = [
        CriterionJudgment(
            criterion="자격1", status="충족", evidence=None, group="eligibility"
        ),
        CriterionJudgment(
            criterion="평가기준1", status="충족", evidence=None, group="criteria_fit"
        ),
        CriterionJudgment(
            criterion="평가기준2", status="미충족", evidence=None, group="criteria_fit"
        ),
        CriterionJudgment(
            criterion="우대조건1", status="충족", evidence=None, group="bonus_fit"
        ),
    ]

    result = aggregate_secondary_score(judgments)

    # criteria_fit 평균 = (1.0 + 0.0) / 2 = 0.5 → 50.0
    assert result.fit_score == pytest.approx(50.0)
    # bonus_fit 평균 = 1.0 → 100.0
    assert result.bonus_score == pytest.approx(100.0)
    # score(자격요건 축)에는 criteria_fit/bonus_fit이 안 섞인다
    assert result.score == pytest.approx(100.0)


def test_aggregate_secondary_score_fit_score_none_without_fit_judgments():
    judgments = [
        CriterionJudgment(
            criterion="자격1", status="충족", evidence=None, group="eligibility"
        ),
    ]

    result = aggregate_secondary_score(judgments)

    assert result.fit_score is None
    assert result.bonus_score is None


async def test_judge_notice_returns_none_when_no_criteria_available():
    notice = NormalizedNoticeSchema.model_validate({})
    profile = CompanyProfile(company_size="소기업", region_name="서울")

    result = await judge_notice(
        profile=profile, plan=_plan(), notice=notice, evidence=[]
    )

    assert result is None


async def test_judge_notice_uses_llm_judgments(monkeypatch):
    async def _fake_judge_criteria(**kwargs):
        return {
            "elig:region": ("충족", "서울 소재 확인"),
            "elig:size": ("충족", "소기업 확인"),
            "excl:reason:0": ("충족", "체납 없음"),
        }

    monkeypatch.setattr(judge_service, "judge_criteria", _fake_judge_criteria)

    profile = CompanyProfile(company_size="소기업", region_name="서울")
    result = await judge_notice(
        profile=profile, plan=_plan(), notice=_notice(), evidence=[]
    )

    assert result is not None
    assert result.excluded is False
    assert result.score == pytest.approx(100.0)


async def test_judge_notice_include_fit_populates_fit_and_bonus_score(monkeypatch):
    async def _fake_judge_criteria(**kwargs):
        return {
            "elig:region": ("충족", "서울 소재 확인"),
            "elig:size": ("충족", "소기업 확인"),
            "excl:reason:0": ("충족", "체납 없음"),
            "fit:criteria:0": ("충족", "AI 비전 검사 기술 보유"),
            "fit:bonus:0": ("충족", "여성기업 확인"),
        }

    monkeypatch.setattr(judge_service, "judge_criteria", _fake_judge_criteria)

    notice = NormalizedNoticeSchema.model_validate(
        {
            "eligibility": {
                "target_regions": ["서울", "경기"],
                "target_company_size": ["소기업"],
            },
            "evaluation": {
                "disqualification_reasons": ["휴업 중인 기업"],
                "criteria": ["기술 혁신성"],
                "preferred_conditions": ["여성기업 우대"],
            },
        }
    )
    profile = CompanyProfile(company_size="소기업", region_name="서울")
    result = await judge_notice(
        profile=profile, plan=_plan(), notice=notice, evidence=[], include_fit=True
    )

    assert result is not None
    assert result.fit_score == pytest.approx(100.0)
    assert result.bonus_score == pytest.approx(100.0)


async def test_judge_notice_without_include_fit_leaves_fit_score_none(monkeypatch):
    async def _fake_judge_criteria(**kwargs):
        return {"elig:region": ("충족", "서울 소재 확인")}

    monkeypatch.setattr(judge_service, "judge_criteria", _fake_judge_criteria)

    profile = CompanyProfile(company_size="소기업", region_name="서울")
    result = await judge_notice(
        profile=profile, plan=_plan(), notice=_notice(), evidence=[]
    )

    assert result is not None
    assert result.fit_score is None
    assert result.bonus_score is None


async def test_judge_notice_falls_back_to_information_lacking_on_ai_error(monkeypatch):
    async def _raise(**kwargs):
        raise judge_service.AiJudgeError("boom")

    monkeypatch.setattr(judge_service, "judge_criteria", _raise)

    profile = CompanyProfile(company_size="소기업", region_name="서울")
    result = await judge_notice(
        profile=profile, plan=_plan(), notice=_notice(), evidence=[]
    )

    assert result is not None
    assert all(judgment.status == "정보부족" for judgment in result.judgments)
    # 모든 판정이 정보부족(가중치 0.5)이면 자격/제외 그룹 평균이 둘 다 0.5라
    # 70/30 가중을 적용해도 결과는 그대로 50.0 = NEUTRAL_SCORE다.
    assert result.score == pytest.approx(NEUTRAL_SCORE)

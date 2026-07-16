import asyncio

import pytest

from app.models.company import CompanyProfile
from app.models.notice import Notice
from app.schemas.business_plan import NormalizedBusinessPlanSchema
from app.schemas.notice_normalization import NormalizedNoticeSchema
from app.services import matching_service
from app.services.matching_service import (
    _eligibility_score,
    _quality_errors,
    _score_notice,
    run_matching,
)


def _plan() -> NormalizedBusinessPlanSchema:
    return NormalizedBusinessPlanSchema.model_validate(
        {
            "company": {"industry": "AI manufacturing"},
            "problem": {"background": "Manual defect inspection is slow."},
            "solution": {
                "summary": "AI vision inspection for smart factory manufacturers.",
                "product_description": "Vision AI detects product defects.",
                "tech_stack": ["AI", "vision", "manufacturing"],
                "differentiators": ["fast deployment"],
            },
            "market": {"target_market": "smart factory"},
            "funding": {
                "scale_up_strategy": "expand pilots with manufacturing customers"
            },
            "team": {"capabilities": "AI and manufacturing experience"},
        }
    )


def _notice_json() -> dict:
    return {
        "basic": {"title": "AI smart factory support", "category": "R&D"},
        "support": {
            "summary": "AI smart factory commercialization support",
            "support_type": ["R&D"],
            "support_content": ["AI pilot", "prototype"],
        },
        "eligibility": {
            "target_company_size": ["small company"],
            "target_regions": ["nationwide"],
            "target_industries": ["AI", "manufacturing"],
        },
        "evaluation": {"preferred_conditions": ["AI", "smart factory"]},
        "matching": {
            "keywords": ["AI", "manufacturing", "smart factory"],
            "suitable_company_profile": "AI manufacturing company",
            "matching_signals": ["AI", "manufacturing"],
        },
    }


def test_quality_errors_require_matching_ready_notice_fields():
    assert _quality_errors(_notice_json()) == []

    invalid = {"basic": {"title": "partial"}}

    assert "support.summary" in _quality_errors(invalid)
    assert "matching.keywords" in _quality_errors(invalid)


def test_score_notice_returns_recommendation_breakdown():
    notice = Notice(id=1, source_id=1, title="AI smart factory support")
    normalized_notice = NormalizedNoticeSchema.model_validate(_notice_json())
    profile = CompanyProfile(company_size="small company", region_name="Seoul")

    result = _score_notice(
        plan=_plan(),
        profile=profile,
        notice=notice,
        normalized_notice=normalized_notice,
    )

    assert result.total_score is not None
    assert result.total_score >= 60
    assert result.eligibility_status in {"eligible", "needs_review"}
    assert result.result_json["notice_quality"]["status"] == "passed"
    assert result.summary_reason


def test_score_notice_uses_lighter_growth_weight_for_rd_notices():
    """R&D 공고는 평가기준이 기술성/혁신성 위주라 성장성(growth) 겹침이 거의
    없다 — 성장성 가중치를 낮추고 아이템 적합도·AI 정밀판정에 더 실어야
    한다(2026-07-16)."""
    notice = Notice(id=1, source_id=1, title="AI smart factory support")
    normalized_notice = NormalizedNoticeSchema.model_validate(_notice_json())
    profile = CompanyProfile(company_size="small company", region_name="Seoul")

    default_result = _score_notice(
        plan=_plan(),
        profile=profile,
        notice=notice,
        normalized_notice=normalized_notice,
        is_rd=False,
    )
    rd_result = _score_notice(
        plan=_plan(),
        profile=profile,
        notice=notice,
        normalized_notice=normalized_notice,
        is_rd=True,
    )

    default_weights = default_result.result_json["score_breakdown"]["weights"]
    rd_weights = rd_result.result_json["score_breakdown"]["weights"]
    assert rd_weights["growth"] < default_weights["growth"]
    assert rd_weights["item_fit"] > default_weights["item_fit"]
    assert rd_weights["secondary"] > default_weights["secondary"]
    assert sum(rd_weights.values()) == pytest.approx(1.0)
    assert sum(default_weights.values()) == pytest.approx(1.0)


def test_score_notice_applies_llm_fit_score_for_rd_and_fund_notices():
    """criteria_fit/bonus_fit LLM 판정(business_fit/growth/bonus 대체)은
    R&D·자금 공고 전용이다 — 다른 카테고리 매칭 로직에 영향을 주면 안 된다."""
    notice = Notice(id=1, source_id=1, title="AI smart factory support")
    normalized_notice = NormalizedNoticeSchema.model_validate(_notice_json())
    profile = CompanyProfile(company_size="small company", region_name="Seoul")

    default_result = _score_notice(
        plan=_plan(),
        profile=profile,
        notice=notice,
        normalized_notice=normalized_notice,
        is_rd=False,
        llm_fit_score=90.0,
        llm_bonus_score=80.0,
    )
    rd_result = _score_notice(
        plan=_plan(),
        profile=profile,
        notice=notice,
        normalized_notice=normalized_notice,
        is_rd=True,
        llm_fit_score=90.0,
        llm_bonus_score=80.0,
    )
    fund_result = _score_notice(
        plan=_plan(),
        profile=profile,
        notice=notice,
        normalized_notice=normalized_notice,
        is_fund=True,
        llm_fit_score=90.0,
        llm_bonus_score=80.0,
    )

    assert float(default_result.business_fit_score) != pytest.approx(90.0)
    assert float(default_result.bonus_score) != pytest.approx(80.0)
    assert float(rd_result.business_fit_score) == pytest.approx(90.0)
    assert float(rd_result.growth_score) == pytest.approx(90.0)
    assert float(rd_result.bonus_score) == pytest.approx(80.0)
    assert float(fund_result.business_fit_score) == pytest.approx(90.0)
    assert float(fund_result.growth_score) == pytest.approx(90.0)
    assert float(fund_result.bonus_score) == pytest.approx(80.0)
    assert rd_result.result_json["score_sources"]["business_fit"] == "llm"
    assert fund_result.result_json["score_sources"]["business_fit"] == "llm"
    assert default_result.result_json["score_sources"]["business_fit"] == "keyword"


def test_score_notice_does_not_track_llm_exclusion_as_hard_cut():
    notice = Notice(id=1, source_id=1, title="AI smart factory support")
    normalized_notice = NormalizedNoticeSchema.model_validate(_notice_json())
    profile = CompanyProfile(company_size="small company", region_name="Seoul")

    result = _score_notice(
        plan=_plan(),
        profile=profile,
        notice=notice,
        normalized_notice=normalized_notice,
        secondary_filter_score=100.0,
    )

    assert float(result.total_score) > 49.0
    assert "secondary_filter_excluded" not in result.result_json


def test_eligibility_score_hard_cuts_institute_only_applicant_structure():
    # 지역/규모가 완벽히 일치해도, 신청주체가 대학·출연연 전용이면 기업은
    # 애초에 신청 자체를 못 하므로 다른 조건과 무관하게 무조건 탈락시켜야
    # 한다(R&D 공고 실측 300건 기준 80%가 컨소시엄/연구기관 구조).
    notice_json = _notice_json()
    notice_json["eligibility"][
        "applicant_structure"
    ] = "컨소시엄·기관 전용(기업 참여 불가)"
    normalized_notice = NormalizedNoticeSchema.model_validate(notice_json)
    profile = CompanyProfile(company_size="small company", region_name="Seoul")

    score, status, cautions, notes = _eligibility_score(profile, normalized_notice)

    assert score <= 20.0
    assert status == "likely_ineligible"
    assert any("대학·연구기관 전용" in caution for caution in cautions)
    assert any(note["sign"] == "-" for note in notes)


def test_eligibility_score_warns_but_does_not_cut_open_consortium():
    # 컨소시엄이 필요해도 기업이 주관/참여 가능한 구조면 하드컷하지 않는다
    # — 파트너 섭외 여부는 신청 시점 상황이지 사업계획서로 알 수 있는 정보가
    # 아니므로, 점수는 그대로 두고 안내 문구만 추가한다.
    notice_json = _notice_json()
    notice_json["eligibility"][
        "applicant_structure"
    ] = "컨소시엄 필요(기업 주관/참여 가능)"
    normalized_notice = NormalizedNoticeSchema.model_validate(notice_json)
    profile = CompanyProfile(company_size="small company", region_name="Seoul")

    score, status, cautions, notes = _eligibility_score(profile, normalized_notice)

    assert status != "likely_ineligible"
    assert any("컨소시엄(공동 신청) 구성이 필요" in caution for caution in cautions)
    assert any("컨소시엄(공동 신청) 구성이 필요" in note["detail"] for note in notes)


@pytest.mark.anyio
async def test_run_matching_limits_global_concurrency(monkeypatch):
    """서로 다른 유저의 매칭이 겹쳐도 실제 실행은 세마포어 한도만큼만
    동시에 돈다(2026-07-16, 겹친 요청 하나가 21분 걸린 걸 실측해 추가)."""
    monkeypatch.setattr(
        matching_service, "_matching_pipeline_semaphore", asyncio.Semaphore(1)
    )
    concurrent = 0
    max_concurrent = 0

    async def _fake_locked(session, *, log, plan, profile, max_results):
        nonlocal concurrent, max_concurrent
        concurrent += 1
        max_concurrent = max(max_concurrent, concurrent)
        await asyncio.sleep(0.05)
        concurrent -= 1
        return []

    monkeypatch.setattr(matching_service, "_run_matching_locked", _fake_locked)

    await asyncio.gather(
        *(
            run_matching(None, log=None, plan=None, profile=None, max_results=10)
            for _ in range(3)
        )
    )

    assert max_concurrent == 1

import pytest

from app.models.business_plan import BusinessPlan
from app.models.company import CompanyProfile
from app.models.match import MatchLog
from app.models.notice import Notice
from app.schemas.business_plan import NormalizedBusinessPlanSchema
from app.schemas.notice_normalization import NormalizedNoticeSchema
from app.services import matching_service
from app.services.matching_service import (
    _first_stage_filter,
    _quality_errors,
    _score_notice,
    _second_stage_filter,
    run_matching,
)


def _plan() -> NormalizedBusinessPlanSchema:
    return NormalizedBusinessPlanSchema.model_validate(
        {
            "company": {
                "industry": "AI manufacturing",
                "industry_candidates": [
                    {
                        "label": "R&D",
                        "confidence": 0.9,
                        "reason": "AI manufacturing technology",
                        "source_keywords": ["AI", "manufacturing"],
                    }
                ],
            },
            "problem": {"background": "Manual defect inspection is slow."},
            "solution": {
                "summary": "AI vision inspection for smart factory manufacturers.",
                "product_description": "Vision AI detects product defects.",
                "tech_stack": ["AI", "vision", "manufacturing"],
                "differentiators": ["fast deployment"],
            },
            "market": {"target_market": "smart factory"},
            "funding": {
                "amount_requested": 50_000_000,
                "scale_up_strategy": "expand pilots with manufacturing customers",
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
    first_stage = _first_stage_filter(
        plan=_plan(),
        profile=profile,
        notice=notice,
        normalized_notice=normalized_notice,
    )
    second_stage = _second_stage_filter(
        plan=_plan(),
        profile=profile,
        notice=notice,
        normalized_notice=normalized_notice,
    )

    result = _score_notice(
        plan=_plan(),
        profile=profile,
        notice=notice,
        normalized_notice=normalized_notice,
        first_stage=first_stage,
        second_stage=second_stage,
    )

    assert result.total_score is not None
    assert result.total_score >= 60
    assert result.eligibility_status in {"eligible", "needs_review"}
    assert result.result_json["pipeline_filters"]["first_stage"]["status"] == "pass"
    assert result.result_json["pipeline_filters"]["second_stage"]["status"] == "pass"
    assert result.result_json["notice_quality"]["status"] == "passed"
    assert result.summary_reason


def test_first_stage_filter_drops_clear_region_mismatch():
    notice = Notice(id=1, source_id=1, title="Seoul AI support")
    notice_json = _notice_json()
    notice_json["eligibility"]["target_regions"] = ["Seoul"]
    normalized_notice = NormalizedNoticeSchema.model_validate(notice_json)
    profile = CompanyProfile(company_size="small company", region_name="Busan")

    decision = _first_stage_filter(
        plan=_plan(),
        profile=profile,
        notice=notice,
        normalized_notice=normalized_notice,
    )

    assert decision.status == "drop"
    assert "지원 지역" in decision.reasons[0]


def test_second_stage_filter_drops_clear_company_size_mismatch():
    notice = Notice(id=1, source_id=1, title="Small company support")
    notice_json = _notice_json()
    notice_json["eligibility"]["target_company_size"] = ["small company"]
    normalized_notice = NormalizedNoticeSchema.model_validate(notice_json)
    profile = CompanyProfile(company_size="large enterprise", region_name="Seoul")

    decision = _second_stage_filter(
        plan=_plan(),
        profile=profile,
        notice=notice,
        normalized_notice=normalized_notice,
    )

    assert decision.status == "drop"
    assert "기업 규모" in decision.reasons[0]


def test_second_stage_filter_marks_requested_amount_over_limit_as_review():
    notice = Notice(id=1, source_id=1, title="Prototype support")
    notice_json = _notice_json()
    notice_json["support"]["support_amount"] = "최대 3천만원"
    normalized_notice = NormalizedNoticeSchema.model_validate(notice_json)
    profile = CompanyProfile(company_size="small company", region_name="Seoul")
    plan = _plan().model_copy(
        update={
            "funding": _plan().funding.model_copy(
                update={"amount_requested": 50_000_000}
            )
        }
    )

    decision = _second_stage_filter(
        plan=plan,
        profile=profile,
        notice=notice,
        normalized_notice=normalized_notice,
    )

    assert decision.status == "review"
    assert "요청 금액" in decision.reasons[0]


@pytest.mark.anyio
async def test_run_matching_stores_pipeline_summary_and_filters_dropped_notices(
    monkeypatch,
):
    good_notice = Notice(
        id=1,
        source_id=1,
        title="AI smart factory support",
        normalized_json=_notice_json(),
    )
    region_drop_json = _notice_json()
    region_drop_json["eligibility"]["target_regions"] = ["Busan"]
    region_drop_notice = Notice(
        id=2,
        source_id=1,
        title="Busan-only support",
        normalized_json=region_drop_json,
    )
    quality_drop_notice = Notice(
        id=3,
        source_id=1,
        title="Partial support",
        normalized_json={"basic": {"title": "Partial support"}},
    )
    saved_results = []

    async def fake_list_candidates(session, *, limit=200):
        return [good_notice, region_drop_notice, quality_drop_notice]

    async def fake_replace_results(session, match_log_id, results):
        saved_results.extend(results)

    monkeypatch.setattr(
        matching_service.match_log_repository,
        "list_normalized_notice_candidates",
        fake_list_candidates,
    )
    monkeypatch.setattr(
        matching_service.match_log_repository,
        "replace_results",
        fake_replace_results,
    )

    log = MatchLog(id=10, run_status="processing")
    plan = BusinessPlan(id=20, analysis_json=_plan().model_dump(mode="json"))
    profile = CompanyProfile(company_size="small company", region_name="Seoul")

    results = await run_matching(
        object(),
        log=log,
        plan=plan,
        profile=profile,
        max_results=5,
    )

    assert results == saved_results
    assert [result.notice_id for result in results] == [good_notice.id]
    assert log.run_status == "completed"
    assert log.query_json["pipeline"]["input_count"] == 3
    assert log.query_json["pipeline"]["quality_filter"]["dropped_count"] == 1
    assert log.query_json["pipeline"]["first_stage_filter"]["drop"] == 1
    assert log.query_json["pipeline"]["scoring"]["selected_notice_ids"] == [1]
    assert results[0].result_json["pipeline_filters"]["first_stage"]["status"] == "pass"

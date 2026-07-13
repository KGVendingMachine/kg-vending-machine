from app.models.company import CompanyProfile
from app.models.notice import Notice
from app.schemas.business_plan import NormalizedBusinessPlanSchema
from app.schemas.notice_normalization import NormalizedNoticeSchema
from app.services.matching_service import _quality_errors, _score_notice


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

from datetime import date

import pytest

from app.api.match_log import create_match_log, list_match_results
from app.models.business_plan import BusinessPlan
from app.models.company import CompanyProfile
from app.models.notice import Notice
from app.models.notice_source import NoticeSource
from app.models.user import User
from app.schemas.business_plan import JobStatus
from app.schemas.match_log import MatchLogCreateRequest

pytestmark = pytest.mark.anyio


def _business_plan_json() -> dict:
    return {
        "schema_version": "1.0",
        "company": {"industry": "AI manufacturing"},
        "problem": {
            "background": "Small manufacturers need AI quality inspection.",
            "target_customer_pain_point": "Manual defect checks are slow.",
            "market_problem": "Factory automation demand is growing.",
        },
        "solution": {
            "summary": "AI vision inspection SaaS for smart factories.",
            "product_description": "Computer vision model detects defects.",
            "tech_stack": ["AI", "vision", "manufacturing"],
            "differentiators": ["low-cost deployment", "fast model training"],
        },
        "market": {
            "target_market": "smart factory",
            "target_customer_persona": "small manufacturer",
        },
        "funding": {
            "use_of_funds": ["model development", "pilot deployment"],
            "scale_up_strategy": "enter smart factory customers and expand pilots",
        },
        "team": {
            "members": ["CEO", "AI engineer"],
            "capabilities": "AI model development and manufacturing domain experience",
        },
    }


def _notice_json(title: str, keywords: list[str]) -> dict:
    return {
        "schema_version": "1.0",
        "basic": {
            "title": title,
            "category": "commercialization",
            "status": "open",
        },
        "application": {"method": "online"},
        "support": {
            "summary": "Supports AI smart factory commercialization.",
            "support_type": ["commercialization", "R&D"],
            "support_content": ["prototype", "pilot", "AI solution"],
        },
        "eligibility": {
            "target_company_size": ["small company"],
            "target_regions": ["nationwide"],
            "target_industries": ["AI", "manufacturing"],
        },
        "evaluation": {"preferred_conditions": ["AI", "smart factory"]},
        "documents": {"required_documents": ["business plan"]},
        "contact": {},
        "matching": {
            "keywords": keywords,
            "suitable_company_profile": "AI manufacturing startup",
            "matching_signals": ["AI", "manufacturing", "smart factory"],
            "caution_points": [],
        },
    }


async def _make_user(db_session, kakao_id: str) -> User:
    user = User(kakao_id=kakao_id, status="ACTIVE", role="USER")
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_plan(db_session, profile: CompanyProfile) -> BusinessPlan:
    plan = BusinessPlan(
        company_profile_id=profile.id,
        title="AI quality inspection plan",
        analysis_status=JobStatus.COMPLETED.value,
        analysis_json=_business_plan_json(),
    )
    db_session.add(plan)
    await db_session.flush()
    return plan


async def _make_notice_source(db_session) -> NoticeSource:
    source = NoticeSource(
        source_name="test-match-source",
        base_url="https://example.com",
        collect_type="test",
    )
    db_session.add(source)
    await db_session.flush()
    return source


async def _make_notice(
    db_session,
    source: NoticeSource,
    *,
    title: str,
    normalized_json: dict,
    is_actionable: bool = True,
) -> Notice:
    notice = Notice(
        source_id=source.id,
        external_id=title,
        title=title,
        application_end_date=date(2026, 12, 31),
        status="open",
        is_actionable=is_actionable,
        normalized_json=normalized_json,
        normalization_status="completed",
    )
    db_session.add(notice)
    await db_session.flush()
    return notice


async def test_create_match_log_scores_and_persists_results(db_session):
    user = await _make_user(db_session, "match-user")
    profile = CompanyProfile(
        user_id=user.id,
        company_size="small company",
        company_stage="startup",
        region_name="Seoul",
    )
    db_session.add(profile)
    await db_session.flush()
    plan = await _make_plan(db_session, profile)
    source = await _make_notice_source(db_session)

    strong_notice = await _make_notice(
        db_session,
        source,
        title="AI smart factory support",
        normalized_json=_notice_json(
            "AI smart factory support", ["AI", "manufacturing", "vision"]
        ),
    )
    await _make_notice(
        db_session,
        source,
        title="low quality notice",
        normalized_json={"basic": {"title": "low quality notice"}},
    )

    response = await create_match_log(
        payload=MatchLogCreateRequest(business_plan_id=plan.id, max_results=5),
        current_user=user,
        session=db_session,
    )

    assert response.run_status == JobStatus.COMPLETED

    results = await list_match_results(
        match_log_id=response.id,
        current_user=user,
        session=db_session,
    )
    assert len(results) == 1
    assert results[0].notice_id == strong_notice.id
    assert results[0].total_score is not None
    assert results[0].result_json["notice_quality"]["status"] == "passed"
    assert results[0].recommendation_level in {"strong", "recommended", "normal"}


async def test_create_match_log_rejects_unanalyzed_plan(db_session):
    user = await _make_user(db_session, "match-unanalysed-user")
    profile = CompanyProfile(user_id=user.id)
    db_session.add(profile)
    await db_session.flush()
    plan = BusinessPlan(company_profile_id=profile.id, title="draft")
    db_session.add(plan)
    await db_session.flush()

    with pytest.raises(Exception) as exc_info:
        await create_match_log(
            payload=MatchLogCreateRequest(business_plan_id=plan.id),
            current_user=user,
            session=db_session,
        )

    assert getattr(exc_info.value, "status_code", None) == 409

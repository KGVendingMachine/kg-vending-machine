from datetime import date

import pytest

from sqlalchemy import select

from app.api.match_log import create_match_log, delete_match_log, list_match_results
from app.models.business_plan import BusinessPlan
from app.models.company import CompanyProfile
from app.models.match import MatchLog, MatchReport, MatchResult
from app.models.notice import Notice
from app.models.notice_source import NoticeSource
from app.models.user import User
from app.repositories import match_log_repository
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
    low_quality_notice = await _make_notice(
        db_session,
        source,
        title="low quality notice",
        normalized_json={"basic": {"title": "low quality notice"}},
    )

    # 로컬 DB에 실제 정규화된 공고가 있어도 밀려나지 않게 여유 있게 요청한다.
    response = await create_match_log(
        payload=MatchLogCreateRequest(business_plan_id=plan.id, max_results=50),
        current_user=user,
        session=db_session,
    )

    assert response.run_status == JobStatus.COMPLETED

    results = await list_match_results(
        match_log_id=response.id,
        current_user=user,
        session=db_session,
    )
    # 개발 DB에 이미 있는 공고가 결과에 섞일 수 있으므로(conftest는 실제 DB 위
    # 트랜잭션 롤백 방식) 이 테스트가 만든 공고 기준으로만 단언한다.
    ours = [r for r in results if r.notice_id == strong_notice.id]
    assert len(ours) == 1
    assert ours[0].total_score is not None
    assert ours[0].result_json["notice_quality"]["status"] == "passed"
    assert ours[0].recommendation_level in {"strong", "recommended", "normal"}
    # 필수 필드가 빈 공고는 품질 게이트에서 제외된다.
    assert all(r.notice_id != low_quality_notice.id for r in results)


async def test_create_match_log_fails_when_no_normalized_notices(
    db_session, monkeypatch
):
    """정규화된 공고가 0건이면 빈 결과로 완료하지 않고 409로 실패해야 한다."""
    user = await _make_user(db_session, "match-empty-user")
    profile = CompanyProfile(user_id=user.id)
    db_session.add(profile)
    await db_session.flush()
    plan = await _make_plan(db_session, profile)

    async def _no_candidates(session, *, limit=200):
        return []

    monkeypatch.setattr(
        match_log_repository, "list_normalized_notice_candidates", _no_candidates
    )

    with pytest.raises(Exception) as exc_info:
        await create_match_log(
            payload=MatchLogCreateRequest(business_plan_id=plan.id),
            current_user=user,
            session=db_session,
        )

    assert getattr(exc_info.value, "status_code", None) == 409

    # 실행 이력은 failed로 남는다.
    row = await db_session.execute(select(MatchLog).where(MatchLog.user_id == user.id))
    log = row.scalar_one()
    assert log.run_status == JobStatus.FAILED.value


async def test_delete_match_log_removes_log_and_children(db_session):
    user = await _make_user(db_session, "match-delete-user")
    profile = CompanyProfile(user_id=user.id)
    db_session.add(profile)
    await db_session.flush()
    plan = await _make_plan(db_session, profile)
    source = await _make_notice_source(db_session)
    await _make_notice(
        db_session,
        source,
        title="AI smart factory support",
        normalized_json=_notice_json(
            "AI smart factory support", ["AI", "manufacturing", "vision"]
        ),
    )

    created = await create_match_log(
        payload=MatchLogCreateRequest(business_plan_id=plan.id, max_results=50),
        current_user=user,
        session=db_session,
    )
    db_session.add(MatchReport(match_run_id=created.id, content="report"))
    await db_session.flush()

    response = await delete_match_log(
        match_log_id=created.id, current_user=user, session=db_session
    )

    assert response.match_log_id == created.id
    assert response.deleted is True
    assert await db_session.get(MatchLog, created.id) is None
    remaining_results = await db_session.execute(
        select(MatchResult).where(MatchResult.recommendation_run_id == created.id)
    )
    assert remaining_results.scalars().all() == []
    remaining_reports = await db_session.execute(
        select(MatchReport).where(MatchReport.match_run_id == created.id)
    )
    assert remaining_reports.scalars().all() == []


async def test_delete_match_log_rejects_other_users_log(db_session):
    owner = await _make_user(db_session, "match-owner")
    other_user = await _make_user(db_session, "match-other")
    profile = CompanyProfile(user_id=owner.id)
    db_session.add(profile)
    await db_session.flush()
    plan = await _make_plan(db_session, profile)

    log = await match_log_repository.create(
        db_session,
        user_id=owner.id,
        company_profile_id=profile.id,
        business_plan_id=plan.id,
        run_status=JobStatus.COMPLETED.value,
    )

    with pytest.raises(Exception) as exc_info:
        await delete_match_log(
            match_log_id=log.id, current_user=other_user, session=db_session
        )

    assert getattr(exc_info.value, "status_code", None) == 404
    assert await db_session.get(MatchLog, log.id) is not None


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

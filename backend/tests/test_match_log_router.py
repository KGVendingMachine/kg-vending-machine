from datetime import date

import pytest
from fastapi import BackgroundTasks, HTTPException

from sqlalchemy import select

from app.api.match_log import (
    _run_matching_job,
    create_match_log,
    delete_match_log,
    list_match_results,
)
from app.models.business_plan import BusinessPlan
from app.models.company import CompanyProfile
from app.models.match import MatchLog, MatchReport, MatchResult
from app.models.notice import Notice
from app.models.notice_source import NoticeSource
from app.models.user import User
from app.repositories import match_log_repository
from app.schemas.business_plan import JobStatus
from app.schemas.match_log import MatchLogCreateRequest
from app.services import matching_service
from app.services.notice_eligibility_service import EligibilityResult

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
        status="모집중",
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
        background_tasks=BackgroundTasks(),
        current_user=user,
        session=db_session,
    )

    # 매칭(OCR·정규화·임베딩·LLM 판정)이 실측 몇 분까지 걸려 요청-응답 안에서
    # 동기로 안 끝낸다 — 즉시 processing으로 응답하고 백그라운드로 넘어간다
    # (2026-07-15, 배포에서 프록시 게이트웨이 타임아웃에 걸리던 문제 수정).
    assert response.run_status == JobStatus.PROCESSING

    # 실제 배포에서는 _execute_matching_job이 별도 세션을 열어 백그라운드로
    # 돌지만, 테스트는 트랜잭션 격리를 위해 내부 로직(_run_matching_job)에
    # db_session을 직접 넣어 실행한다(test_run_normalization_job_* 패턴과 동일).
    await _run_matching_job(
        db_session, response.id, business_plan_id=plan.id, max_results=50
    )

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


async def test_create_match_log_excludes_notices_filtered_out_by_eligibility(
    db_session, monkeypatch
):
    """1차 하드필터(get_eligible_notices)가 걸러낸 공고는 품질 기준을
    충족하더라도 2차 필터링/최종 결과에 도달하지 못해야 한다."""
    user = await _make_user(db_session, "match-eligibility-user")
    profile = CompanyProfile(
        user_id=user.id,
        company_size="small company",
        company_stage="startup",
        region_name="Seoul",
        region_code="11",
    )
    db_session.add(profile)
    await db_session.flush()
    plan = await _make_plan(db_session, profile)
    source = await _make_notice_source(db_session)

    eligible_notice = await _make_notice(
        db_session,
        source,
        title="eligible AI smart factory support",
        normalized_json=_notice_json(
            "eligible AI smart factory support", ["AI", "manufacturing", "vision"]
        ),
    )
    ineligible_notice = await _make_notice(
        db_session,
        source,
        title="ineligible AI smart factory support",
        normalized_json=_notice_json(
            "ineligible AI smart factory support", ["AI", "manufacturing", "vision"]
        ),
    )

    async def _fake_get_eligible_notices(session, profile, today=None):
        # 1차 하드필터를 통과한 공고는 eligible_notice 하나뿐이라고 가정한다
        # — ineligible_notice는 품질 필터를 통과할 수 있는 정상 데이터를
        # 갖고 있어도 애초에 후보 목록에 들지 못해야 한다.
        return EligibilityResult(
            notice_ids=[eligible_notice.id], counts={"input": 2, "통과": 1}
        )

    monkeypatch.setattr(
        matching_service, "get_eligible_notices", _fake_get_eligible_notices
    )

    # 매칭은 백그라운드 잡으로 도니(2026-07-15) 즉시 completed가 아니라
    # processing으로 응답한다 — 다른 테스트와 같은 패턴으로 _run_matching_job을
    # 직접 실행해 완료 상태까지 만든다.
    response = await create_match_log(
        payload=MatchLogCreateRequest(business_plan_id=plan.id, max_results=50),
        background_tasks=BackgroundTasks(),
        current_user=user,
        session=db_session,
    )
    assert response.run_status == JobStatus.PROCESSING

    await _run_matching_job(
        db_session, response.id, business_plan_id=plan.id, max_results=50
    )

    results = await list_match_results(
        match_log_id=response.id,
        current_user=user,
        session=db_session,
    )
    notice_ids = {r.notice_id for r in results}
    assert eligible_notice.id in notice_ids
    assert ineligible_notice.id not in notice_ids


async def test_create_match_log_marks_failed_when_no_normalized_notices(
    db_session, monkeypatch
):
    """정규화된 공고가 0건이면 빈 결과로 완료 처리하지 않고 run_status가
    failed로 남아야 한다. 실행이 백그라운드로 넘어가므로(2026-07-15) 더 이상
    create_match_log 자체가 409를 던지지 않는다 — 실패는 job 실행 이후에만
    확인 가능하다."""
    user = await _make_user(db_session, "match-empty-user")
    profile = CompanyProfile(user_id=user.id)
    db_session.add(profile)
    await db_session.flush()
    plan = await _make_plan(db_session, profile)

    async def _no_candidates(session, *, notice_ids=None):
        return []

    monkeypatch.setattr(
        match_log_repository, "list_normalized_notice_candidates", _no_candidates
    )

    response = await create_match_log(
        payload=MatchLogCreateRequest(business_plan_id=plan.id),
        background_tasks=BackgroundTasks(),
        current_user=user,
        session=db_session,
    )
    assert response.run_status == JobStatus.PROCESSING

    await _run_matching_job(
        db_session, response.id, business_plan_id=plan.id, max_results=10
    )

    row = await db_session.execute(select(MatchLog).where(MatchLog.id == response.id))
    log = row.scalar_one()
    assert log.run_status == JobStatus.FAILED.value


async def test_create_match_log_reuses_existing_processing_log_for_same_plan(
    db_session,
):
    """같은 계획서로 매칭이 이미 processing 중일 때 재요청하면, 새로 만들지
    않고 기존 로그를 그대로 돌려줘야 한다(배경: 겹친 요청이 세마포어·OpenAI
    호출 한도를 나눠 써서 하나가 비정상적으로 오래 걸리는 문제 실측)."""
    user = await _make_user(db_session, "match-dedup-user")
    profile = CompanyProfile(user_id=user.id)
    db_session.add(profile)
    await db_session.flush()
    plan = await _make_plan(db_session, profile)

    first = await create_match_log(
        payload=MatchLogCreateRequest(business_plan_id=plan.id),
        background_tasks=BackgroundTasks(),
        current_user=user,
        session=db_session,
    )
    second = await create_match_log(
        payload=MatchLogCreateRequest(business_plan_id=plan.id),
        background_tasks=BackgroundTasks(),
        current_user=user,
        session=db_session,
    )

    assert second.id == first.id


async def test_create_match_log_rejects_when_different_plan_already_processing(
    db_session,
):
    """다른 계획서 매칭이 이미 도는 중이면 새 매칭은 409로 막아야 한다 —
    동시에 여러 매칭이 겹치면 자원을 다퉈 느려지는 문제를 예방한다."""
    user = await _make_user(db_session, "match-conflict-user")
    profile = CompanyProfile(user_id=user.id)
    db_session.add(profile)
    await db_session.flush()
    plan_a = await _make_plan(db_session, profile)
    plan_b = await _make_plan(db_session, profile)

    await create_match_log(
        payload=MatchLogCreateRequest(business_plan_id=plan_a.id),
        background_tasks=BackgroundTasks(),
        current_user=user,
        session=db_session,
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_match_log(
            payload=MatchLogCreateRequest(business_plan_id=plan_b.id),
            background_tasks=BackgroundTasks(),
            current_user=user,
            session=db_session,
        )
    assert exc_info.value.status_code == 409


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
        background_tasks=BackgroundTasks(),
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
            background_tasks=BackgroundTasks(),
            current_user=user,
            session=db_session,
        )

    assert getattr(exc_info.value, "status_code", None) == 409

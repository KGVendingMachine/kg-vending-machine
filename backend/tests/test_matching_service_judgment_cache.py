"""
tests/test_matching_service_judgment_cache.py

_judge_top_candidates의 LLM 판정 결과 캐싱(2026-07-16, RAG 성능 개선 검토
— secondary_filtering_judgment 테이블)을 검증한다. 실제 로컬 DB(db_session)
에 저장/조회하되, judge_notice(LLM 호출)와 get_criterion_evidence(임베딩
호출)는 monkeypatch로 대체해 실제 외부 API는 부르지 않는다.
"""

from unittest.mock import AsyncMock

import pytest

from app.models.business_plan import BusinessPlan
from app.models.company import CompanyProfile
from app.models.notice import Notice
from app.models.notice_source import NoticeSource
from app.models.user import User
from app.schemas.business_plan import JobStatus, NormalizedBusinessPlanSchema
from app.schemas.notice_normalization import NormalizedNoticeSchema
from app.services import matching_service
from app.services.matching_service import _judge_top_candidates
from app.services.secondary_filtering_judge_service import (
    CriterionJudgment,
    JudgedSecondaryScore,
)
from app.services.secondary_filtering_service import SecondaryFilteringResult

pytestmark = pytest.mark.anyio


async def _make_fixtures(db_session, *, company_size: str = "소기업"):
    user = User(kakao_id="judgment-cache-test-user", status="ACTIVE", role="USER")
    db_session.add(user)
    await db_session.flush()

    profile = CompanyProfile(
        user_id=user.id, company_size=company_size, region_name="서울"
    )
    db_session.add(profile)
    await db_session.flush()

    plan = BusinessPlan(
        company_profile_id=profile.id,
        title="테스트 사업계획서",
        analysis_status=JobStatus.COMPLETED.value,
        analysis_json={},
    )
    db_session.add(plan)
    await db_session.flush()

    source = NoticeSource(
        source_name="judgment-cache-test-source",
        base_url="https://example.com",
        collect_type="test",
    )
    db_session.add(source)
    await db_session.flush()

    notice = Notice(
        source_id=source.id,
        external_id="judgment-cache-test-notice",
        title="캐시 테스트 공고",
        normalized_json={},
    )
    db_session.add(notice)
    await db_session.flush()

    normalized_notice = NormalizedNoticeSchema.model_validate({})
    return profile, plan, notice, normalized_notice


def _judged_score() -> JudgedSecondaryScore:
    return JudgedSecondaryScore(
        score=77.5,
        excluded=False,
        judgments=[
            CriterionJudgment(
                criterion="지역 요건",
                status="충족",
                evidence="서울 소재",
                group="eligibility",
            )
        ],
    )


async def test_second_matching_run_reuses_cached_judgment(db_session, monkeypatch):
    profile, plan, notice, normalized_notice = await _make_fixtures(db_session)
    secondary_result = SecondaryFilteringResult(scores={notice.id: 90.0}, evidence={})

    judge_notice_mock = AsyncMock(return_value=_judged_score())
    monkeypatch.setattr(matching_service, "judge_notice", judge_notice_mock)
    monkeypatch.setattr(
        matching_service,
        "build_criteria_statements",
        lambda notice, include_fit=False: ["지역 요건"],
    )
    monkeypatch.setattr(
        matching_service,
        "get_criterion_evidence",
        AsyncMock(return_value=[]),
    )

    kwargs = dict(
        session=db_session,
        log_id=1,
        business_plan_id=plan.id,
        plan=NormalizedBusinessPlanSchema.model_validate({}),
        profile=profile,
        secondary_result=secondary_result,
        passed=[(notice, normalized_notice)],
        fit_judged_notice_ids=set(),
    )

    first_scores, first_judged = await _judge_top_candidates(**kwargs)
    second_scores, second_judged = await _judge_top_candidates(**kwargs)

    judge_notice_mock.assert_awaited_once()  # 두 번째 호출은 캐시로 대체됨
    assert first_scores[notice.id] == pytest.approx(77.5)
    assert second_scores[notice.id] == pytest.approx(77.5)
    assert second_judged[notice.id].judgments[0].criterion == "지역 요건"


async def test_profile_change_invalidates_cache(db_session, monkeypatch):
    profile, plan, notice, normalized_notice = await _make_fixtures(
        db_session, company_size="소기업"
    )
    secondary_result = SecondaryFilteringResult(scores={notice.id: 90.0}, evidence={})

    judge_notice_mock = AsyncMock(return_value=_judged_score())
    monkeypatch.setattr(matching_service, "judge_notice", judge_notice_mock)
    monkeypatch.setattr(
        matching_service,
        "build_criteria_statements",
        lambda notice, include_fit=False: ["지역 요건"],
    )
    monkeypatch.setattr(
        matching_service,
        "get_criterion_evidence",
        AsyncMock(return_value=[]),
    )

    base_kwargs = dict(
        session=db_session,
        log_id=1,
        business_plan_id=plan.id,
        plan=NormalizedBusinessPlanSchema.model_validate({}),
        secondary_result=secondary_result,
        passed=[(notice, normalized_notice)],
        fit_judged_notice_ids=set(),
    )

    await _judge_top_candidates(profile=profile, **base_kwargs)

    profile.company_size = "중기업"  # 프로필 변경 -> 지문(fingerprint)이 달라짐
    await db_session.flush()
    await _judge_top_candidates(profile=profile, **base_kwargs)

    assert judge_notice_mock.await_count == 2  # 프로필이 바뀌어 캐시 미스

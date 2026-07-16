"""
tests/test_match_log_repository.py

mark_stale_processing_as_failed (2026-07-16 추가) 검증 — 서버가 재시작되면
이전 프로세스의 백그라운드 매칭 잡을 이어받을 방법이 없어, processing에
멈춰있던 행만 failed로 정리하고 나머지 상태는 건드리지 않아야 한다.
"""

import pytest

from app.models.company import CompanyProfile
from app.models.match import MatchLog
from app.models.user import User
from app.repositories import match_log_repository

pytestmark = pytest.mark.anyio


async def _make_user_and_profile(db_session) -> CompanyProfile:
    user = User(kakao_id="stale-match-user", status="ACTIVE", role="USER")
    db_session.add(user)
    await db_session.flush()
    profile = CompanyProfile(user_id=user.id)
    db_session.add(profile)
    await db_session.flush()
    return profile


async def _make_log(db_session, profile: CompanyProfile, run_status: str) -> MatchLog:
    log = MatchLog(
        user_id=profile.user_id,
        company_profile_id=profile.id,
        run_status=run_status,
    )
    db_session.add(log)
    await db_session.flush()
    return log


async def test_mark_stale_processing_as_failed_only_touches_processing(db_session):
    # db_session은 실제(터널로 붙는 운영) DB 위 트랜잭션이라, 이 테스트와
    # 무관하게 이미 processing인 행이 있을 수 있다 — recovered 총합이 아니라
    # 이 테스트가 만든 행들의 상태 변화만 검증한다(전체 개수 단언은 공유 DB
    # 상태에 따라 흔들려 신뢰할 수 없음).
    profile = await _make_user_and_profile(db_session)
    stale = await _make_log(db_session, profile, "processing")
    completed = await _make_log(db_session, profile, "completed")
    failed = await _make_log(db_session, profile, "failed")

    recovered = await match_log_repository.mark_stale_processing_as_failed(db_session)
    await db_session.flush()

    assert recovered >= 1
    await db_session.refresh(stale)
    await db_session.refresh(completed)
    await db_session.refresh(failed)
    assert stale.run_status == "failed"
    assert completed.run_status == "completed"
    assert failed.run_status == "failed"


async def test_mark_stale_processing_as_failed_leaves_completed_untouched(db_session):
    profile = await _make_user_and_profile(db_session)
    completed = await _make_log(db_session, profile, "completed")

    await match_log_repository.mark_stale_processing_as_failed(db_session)
    await db_session.flush()

    await db_session.refresh(completed)
    assert completed.run_status == "completed"

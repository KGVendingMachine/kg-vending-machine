"""tests/test_auth_service.py

카카오 로그인의 계정 상태 정책 검증: BLOCKED는 로그인 거부,
WITHDRAWN은 재가입(재활성화) 처리. 카카오 API는 monkeypatch로 대체한다.
탈퇴 시 딸린 데이터(기업 프로필/사업계획서/매칭 기록)가 연쇄 삭제되는지도 검증한다.
"""

import pytest
from sqlalchemy import select

from app.models.business_plan import BusinessPlan, BusinessPlanChunk
from app.models.company import CompanyProfile
from app.models.match import MatchLog, MatchReport, MatchResult
from app.models.notice import Notice
from app.models.notice_bookmark import NoticeBookmark
from app.models.notice_source import NoticeSource
from app.models.user import User
from app.services.auth_service import (
    InactiveAccountError,
    login_with_kakao,
    withdraw_account,
)
from app.utils import kakao_client

pytestmark = pytest.mark.anyio

KAKAO_ID = "auth-service-test-kakao"


def _patch_kakao(monkeypatch, nickname: str = "새닉네임") -> None:
    """카카오 토큰 교환/사용자 조회를 가짜 응답으로 바꾼다."""

    async def fake_exchange(code: str) -> str:
        return "fake-kakao-access-token"

    async def fake_fetch(token: str) -> dict:
        return {
            "id": KAKAO_ID,
            "kakao_account": {"profile": {"nickname": nickname}},
        }

    monkeypatch.setattr(kakao_client, "exchange_code_for_token", fake_exchange)
    monkeypatch.setattr(kakao_client, "fetch_kakao_user", fake_fetch)


async def _make_user(db_session, status: str) -> User:
    user = User(kakao_id=KAKAO_ID, status=status)
    db_session.add(user)
    await db_session.flush()
    return user


async def test_login_blocked_account_rejected(db_session, monkeypatch):
    await _make_user(db_session, status="BLOCKED")
    _patch_kakao(monkeypatch)

    with pytest.raises(InactiveAccountError):
        await login_with_kakao(db_session, "dummy-code")


async def test_login_withdrawn_account_reactivates(db_session, monkeypatch):
    user = await _make_user(db_session, status="WITHDRAWN")
    _patch_kakao(monkeypatch, nickname="돌아온닉")

    tokens = await login_with_kakao(db_session, "dummy-code")

    assert tokens["user_id"] == user.id
    # upsert가 raw SQL로 갱신해 identity map의 객체가 stale할 수 있어
    # DB에서 다시 읽는다(운영은 요청마다 새 세션이라 해당 없음).
    await db_session.refresh(user)
    assert user.status == "ACTIVE"
    # 익명화로 지웠던 프로필이 카카오 값으로 다시 채워진다.
    assert user.nickname == "돌아온닉"


async def test_login_active_account_stays_active(db_session, monkeypatch):
    user = await _make_user(db_session, status="ACTIVE")
    _patch_kakao(monkeypatch)

    tokens = await login_with_kakao(db_session, "dummy-code")

    assert tokens["user_id"] == user.id
    assert tokens["access_token"] and tokens["refresh_token"]


# --- withdraw_account: 딸린 데이터 연쇄 삭제 -----------------------------------


async def _make_full_account(db_session, user: User) -> dict:
    """company_profile부터 match_result/report까지 유저 데이터 전체를 만든다."""
    profile = CompanyProfile(
        user_id=user.id,
        representative_name="홍길동",
        business_registration_number="123-45-67890",
        file_url="storage/uploads/profile-fake.txt",
    )
    db_session.add(profile)
    await db_session.flush()

    plan = BusinessPlan(
        company_profile_id=profile.id,
        raw_text="사업계획서 원문",
        file_url="storage/uploads/plan-fake.txt",
    )
    db_session.add(plan)
    await db_session.flush()

    chunk = BusinessPlanChunk(business_plan_id=plan.id, chunk_text="청크")
    db_session.add(chunk)

    source = NoticeSource(
        source_name="withdraw-test-source",
        base_url="https://example.com",
        collect_type="test",
    )
    db_session.add(source)
    await db_session.flush()

    notice = Notice(source_id=source.id, external_id="withdraw-notice", title="공고")
    db_session.add(notice)
    await db_session.flush()

    log = MatchLog(
        user_id=user.id, company_profile_id=profile.id, business_plan_id=plan.id
    )
    db_session.add(log)
    await db_session.flush()

    result = MatchResult(recommendation_run_id=log.id, notice_id=notice.id)
    report = MatchReport(match_run_id=log.id, content="리포트")
    bookmark = NoticeBookmark(user_id=user.id, notice_id=notice.id)
    db_session.add_all([result, report, bookmark])
    await db_session.flush()

    return {
        "profile_id": profile.id,
        "plan_id": plan.id,
        "chunk_id": chunk.id,
        "log_id": log.id,
        "result_id": result.id,
        "report_id": report.id,
        "bookmark_id": bookmark.id,
    }


async def test_withdraw_account_deletes_owned_data(db_session, monkeypatch):
    async def fake_unlink(kakao_id: str) -> None:
        pass

    monkeypatch.setattr(kakao_client, "unlink_user", fake_unlink)
    deleted_files: list[str] = []
    monkeypatch.setattr(
        "app.services.auth_service.delete_stored_file", deleted_files.append
    )

    user = await _make_user(db_session, status="ACTIVE")
    ids = await _make_full_account(db_session, user)

    await withdraw_account(db_session, user)

    assert user.status == "WITHDRAWN"
    assert user.kakao_id == KAKAO_ID  # 재로그인 매칭을 위해 남는다

    for model, id_ in [
        (CompanyProfile, ids["profile_id"]),
        (BusinessPlan, ids["plan_id"]),
        (BusinessPlanChunk, ids["chunk_id"]),
        (MatchLog, ids["log_id"]),
        (MatchResult, ids["result_id"]),
        (MatchReport, ids["report_id"]),
        (NoticeBookmark, ids["bookmark_id"]),
    ]:
        row = await db_session.execute(select(model).where(model.id == id_))
        assert row.scalar_one_or_none() is None, f"{model.__name__} row survived"

    # 파일도 (profile.file_url, plan.file_url) 둘 다 정리 대상으로 넘어간다.
    assert set(deleted_files) == {
        "storage/uploads/profile-fake.txt",
        "storage/uploads/plan-fake.txt",
    }

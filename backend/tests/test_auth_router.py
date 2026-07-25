"""tests/test_auth_router.py

쿠키/Bearer 기반 인증 의존성과 로그아웃·refresh 쿠키 동작 검증.

실제 HTTP 서버 없이 의존성/라우터 함수를 직접 호출한다(다른 라우터 테스트와
동일한 방식). Request는 최소 scope로 만들어 쿠키/헤더만 실어 준다.
"""

import pytest
from fastapi import HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from app.api.auth import dev_login_endpoint, logout, me, refresh, withdraw
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.models.user import User
from app.schemas.auth import DevLoginRequest, RefreshRequest
from app.utils import kakao_client
from app.utils.auth_cookies import (
    ACCESS_TOKEN_COOKIE_NAME,
    REFRESH_TOKEN_COOKIE_NAME,
)
from app.utils.kakao_client import KakaoAuthError
from app.utils.jwt import create_access_token, create_refresh_token

pytestmark = pytest.mark.anyio


def _make_request(cookies: dict[str, str] | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cookies:
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers.append((b"cookie", cookie_header.encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _set_cookie_headers(response: Response) -> list[str]:
    return [v.decode() for k, v in response.raw_headers if k == b"set-cookie"]


async def _make_active_user(db_session, **overrides) -> User:
    defaults = dict(kakao_id="auth-test-kakao", status="ACTIVE", role="USER")
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    await db_session.flush()
    return user


# --- get_current_user: 토큰 소스 ---------------------------------------------


async def test_get_current_user_via_cookie(db_session):
    user = await _make_active_user(db_session)
    token = create_access_token(user.id, role=user.role)
    request = _make_request({ACCESS_TOKEN_COOKIE_NAME: token})

    result = await get_current_user(request, credentials=None, session=db_session)

    assert result.id == user.id


async def test_get_current_user_via_bearer_fallback(db_session):
    user = await _make_active_user(db_session)
    token = create_access_token(user.id, role=user.role)
    request = _make_request()  # 쿠키 없음 → 헤더로 폴백

    result = await get_current_user(
        request, credentials=_bearer(token), session=db_session
    )

    assert result.id == user.id


async def test_get_current_user_prefers_cookie_over_bearer(db_session):
    user = await _make_active_user(db_session)
    good = create_access_token(user.id, role=user.role)
    request = _make_request({ACCESS_TOKEN_COOKIE_NAME: good})

    # Bearer에는 깨진 토큰을 넣어도 쿠키가 우선이라 통과해야 한다.
    result = await get_current_user(
        request, credentials=_bearer("not-a-real-token"), session=db_session
    )

    assert result.id == user.id


async def test_get_current_user_no_token_401(db_session):
    with pytest.raises(HTTPException) as exc:
        await get_current_user(_make_request(), credentials=None, session=db_session)
    assert exc.value.status_code == 401


async def test_get_current_user_rejects_refresh_token(db_session):
    user = await _make_active_user(db_session)
    refresh_token = create_refresh_token(user.id)
    request = _make_request({ACCESS_TOKEN_COOKIE_NAME: refresh_token})

    with pytest.raises(HTTPException) as exc:
        await get_current_user(request, credentials=None, session=db_session)
    assert exc.value.status_code == 401


async def test_get_current_user_inactive_403(db_session):
    user = await _make_active_user(db_session, status="WITHDRAWN")
    token = create_access_token(user.id, role=user.role)
    request = _make_request({ACCESS_TOKEN_COOKIE_NAME: token})

    with pytest.raises(HTTPException) as exc:
        await get_current_user(request, credentials=None, session=db_session)
    assert exc.value.status_code == 403


# --- me ----------------------------------------------------------------------


async def test_me_returns_current_user(db_session):
    user = await _make_active_user(db_session)
    assert await me(current_user=user) is user


# --- logout ------------------------------------------------------------------


async def test_logout_clears_both_cookies():
    response = await logout()
    assert response.status_code == 204

    cookies = "".join(_set_cookie_headers(response)).replace(" ", "")
    assert f"{ACCESS_TOKEN_COOKIE_NAME}=" in cookies and "Max-Age=0" in cookies
    assert f"{REFRESH_TOKEN_COOKIE_NAME}=" in cookies


# --- withdraw ----------------------------------------------------------------


def _patch_unlink(monkeypatch, calls: list[str]) -> None:
    """카카오 unlink 호출을 가짜로 바꾸고 호출된 kakao_id를 기록한다."""

    async def fake_unlink(kakao_id: str) -> None:
        calls.append(kakao_id)

    monkeypatch.setattr(kakao_client, "unlink_user", fake_unlink)


async def test_withdraw_soft_deletes_and_anonymizes(db_session, monkeypatch):
    unlink_calls: list[str] = []
    _patch_unlink(monkeypatch, unlink_calls)
    user = await _make_active_user(
        db_session, email="user@example.com", name="홍길동", nickname="길동이"
    )

    response = await withdraw(current_user=user, session=db_session)

    assert response.status_code == 204
    assert user.status == "WITHDRAWN"
    assert user.email is None
    assert user.name is None
    assert user.nickname is None
    # kakao_id는 재로그인 시 재가입 매칭을 위해 남긴다.
    assert user.kakao_id == "auth-test-kakao"
    # 카카오 연결 끊기가 호출됐다.
    assert unlink_calls == ["auth-test-kakao"]

    # 인증 쿠키도 함께 만료시킨다(로그아웃과 동일).
    cookies = "".join(_set_cookie_headers(response)).replace(" ", "")
    assert f"{ACCESS_TOKEN_COOKIE_NAME}=" in cookies and "Max-Age=0" in cookies
    assert f"{REFRESH_TOKEN_COOKIE_NAME}=" in cookies


async def test_withdraw_aborts_when_unlink_fails(db_session, monkeypatch):
    async def failing_unlink(kakao_id: str) -> None:
        raise KakaoAuthError("카카오 연결 끊기 실패(500)")

    monkeypatch.setattr(kakao_client, "unlink_user", failing_unlink)
    user = await _make_active_user(db_session, nickname="길동이")

    with pytest.raises(HTTPException) as exc:
        await withdraw(current_user=user, session=db_session)

    # 502로 변환되고, DB 변경 없이 탈퇴가 중단돼 재시도할 수 있다.
    assert exc.value.status_code == 502
    assert user.status == "ACTIVE"
    assert user.nickname == "길동이"


async def test_withdrawn_user_token_rejected_403(db_session, monkeypatch):
    _patch_unlink(monkeypatch, [])
    user = await _make_active_user(db_session)
    token = create_access_token(user.id, role=user.role)
    await withdraw(current_user=user, session=db_session)

    # 탈퇴 전 발급된 access token은 즉시 무력화된다.
    request = _make_request({ACCESS_TOKEN_COOKIE_NAME: token})
    with pytest.raises(HTTPException) as exc:
        await get_current_user(request, credentials=None, session=db_session)
    assert exc.value.status_code == 403


# --- dev_login_endpoint: ENVIRONMENT=local 게이트 ------------------------------


async def test_dev_login_endpoint_issues_tokens_when_local(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "ENVIRONMENT", "local")
    user = await _make_active_user(db_session)

    result = await dev_login_endpoint(
        DevLoginRequest(user_id=user.id), session=db_session
    )

    assert result.access_token and result.refresh_token


async def test_dev_login_endpoint_404_outside_local(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "ENVIRONMENT", "production")
    user = await _make_active_user(db_session)

    with pytest.raises(HTTPException) as exc:
        await dev_login_endpoint(DevLoginRequest(user_id=user.id), session=db_session)
    assert exc.value.status_code == 404


async def test_dev_login_endpoint_404_unknown_user(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "ENVIRONMENT", "local")

    with pytest.raises(HTTPException) as exc:
        await dev_login_endpoint(DevLoginRequest(user_id=999_999), session=db_session)
    assert exc.value.status_code == 404


# --- refresh -----------------------------------------------------------------


async def test_refresh_via_cookie_sets_access_cookie(db_session):
    user = await _make_active_user(db_session)
    refresh_token = create_refresh_token(user.id)
    request = _make_request({REFRESH_TOKEN_COOKIE_NAME: refresh_token})
    response = Response()

    result = await refresh(request, response, payload=None, session=db_session)

    assert result.access_token
    cookies = "".join(_set_cookie_headers(response))
    assert f"{ACCESS_TOKEN_COOKIE_NAME}=" in cookies


async def test_refresh_via_body(db_session):
    user = await _make_active_user(db_session)
    refresh_token = create_refresh_token(user.id)
    result = await refresh(
        _make_request(),
        Response(),
        payload=RefreshRequest(refresh_token=refresh_token),
        session=db_session,
    )
    assert result.access_token


async def test_refresh_without_token_401(db_session):
    with pytest.raises(HTTPException) as exc:
        await refresh(_make_request(), Response(), payload=None, session=db_session)
    assert exc.value.status_code == 401

"""tests/test_auth_router.py

쿠키/Bearer 기반 인증 의존성과 로그아웃·refresh 쿠키 동작 검증.

실제 HTTP 서버 없이 의존성/라우터 함수를 직접 호출한다(다른 라우터 테스트와
동일한 방식). Request는 최소 scope로 만들어 쿠키/헤더만 실어 준다.
"""

import pytest
from fastapi import HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from app.api.auth import logout, me, refresh
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.auth import RefreshRequest
from app.utils.auth_cookies import (
    ACCESS_TOKEN_COOKIE_NAME,
    REFRESH_TOKEN_COOKIE_NAME,
)
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

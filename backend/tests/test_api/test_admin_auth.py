"""Tests for require_admin and GET /api/v1/admin/me.

Signs real HS256 tokens with a test secret (same approach as
tests/test_auth/test_jwt_verifier.py's HS256 path) so these tests exercise
require_admin's actual claim-reading logic end to end, rather than bypassing
it with a dependency override.
"""

from __future__ import annotations

import time

import jwt
import pytest

from src.config import get_settings

_SECRET = "test-jwt-secret-that-is-at-least-32-bytes-long"
_SUPABASE_URL = "https://example.supabase.co"
_ISSUER = f"{_SUPABASE_URL}/auth/v1"


@pytest.fixture(autouse=True)
def _configured_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", _SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", _SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_token(*, is_anonymous=False, app_metadata=None, user_metadata=None, **extra_claims):
    now = int(time.time())
    payload = {
        "sub": "admin-user-1",
        "email": "admin@vsftrip.vn",
        "aud": "authenticated",
        "iss": _ISSUER,
        "iat": now,
        "exp": now + 3600,
        "is_anonymous": is_anonymous,
        **extra_claims,
    }
    if app_metadata is not None:
        payload["app_metadata"] = app_metadata
    if user_metadata is not None:
        payload["user_metadata"] = user_metadata
    return jwt.encode(payload, _SECRET, algorithm="HS256")


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_required", ["true", "false"])
async def test_no_token_is_rejected_regardless_of_auth_required(client, monkeypatch, auth_required):
    monkeypatch.setenv("AUTH_REQUIRED", auth_required)
    get_settings.cache_clear()
    response = await client.get("/api/v1/admin/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Chưa đăng nhập."


@pytest.mark.asyncio
async def test_garbled_token_is_401_not_403(client):
    """A malformed/expired token must read as 'log in again' (401), not
    'you're not an admin' (403) -- those tell the frontend to do very
    different things."""
    response = await client.get("/api/v1/admin/me", headers=_auth_header("not-a-real-token"))
    assert response.status_code == 401
    assert response.json()["detail"] == "Phiên đăng nhập không hợp lệ."


@pytest.mark.asyncio
async def test_valid_token_without_admin_role_is_forbidden(client):
    token = _make_token(app_metadata={})
    response = await client.get("/api/v1/admin/me", headers=_auth_header(token))
    assert response.status_code == 403
    assert response.json()["detail"] == "Tài khoản này không có quyền truy cập trang quản trị."


@pytest.mark.asyncio
async def test_user_metadata_role_admin_is_not_honored(client):
    """Anti self-grant: user_metadata is writable by the user themselves via
    supabase.auth.updateUser() -- only app_metadata may confer admin."""
    token = _make_token(app_metadata={}, user_metadata={"role": "admin"})
    response = await client.get("/api/v1/admin/me", headers=_auth_header(token))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_app_metadata_role_admin_is_authorized(client):
    token = _make_token(app_metadata={"role": "admin"})
    response = await client.get("/api/v1/admin/me", headers=_auth_header(token))
    assert response.status_code == 200
    body = response.json()
    assert body == {"id": "admin-user-1", "email": "admin@vsftrip.vn"}


@pytest.mark.asyncio
async def test_anonymous_session_with_admin_role_is_forbidden(client):
    token = _make_token(is_anonymous=True, app_metadata={"role": "admin"})
    response = await client.get("/api/v1/admin/me", headers=_auth_header(token))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_every_admin_route_requires_admin():
    """Guards the plan's #1 risk item going forward: Depends(require_admin)
    must reach every route under /api/v1/admin, including ones a future
    sub-router adds, via the router-level dependency alone -- not a
    per-handler dependency a new handler could forget to add."""
    from fastapi.routing import APIRoute

    from src.auth.admin import require_admin
    from src.main import app

    def _dependency_callables(dependant):
        yield dependant.call
        for sub in dependant.dependencies:
            yield from _dependency_callables(sub)

    unguarded = [
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path.startswith("/api/v1/admin")
        and require_admin not in _dependency_callables(route.dependant)
    ]
    assert unguarded == []

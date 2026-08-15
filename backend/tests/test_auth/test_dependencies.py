"""Unit tests for the get_current_user FastAPI dependency's rollout behavior
(see src/auth/dependencies.py's module docstring for the contract this
verifies): a valid token always identifies the caller; a missing/invalid one
is tolerated as None while AUTH_REQUIRED is off (the default) and rejected
with 401 once it's on."""

import time

import jwt
import pytest
from fastapi import HTTPException

from src.auth.dependencies import get_current_user
from src.config import get_settings

_SECRET = "test-jwt-secret-that-is-at-least-32-bytes-long"
_SUPABASE_URL = "https://example.supabase.co"
_ISSUER = f"{_SUPABASE_URL}/auth/v1"


@pytest.fixture(autouse=True)
def _configured_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", _SECRET)
    monkeypatch.setenv("SUPABASE_URL", _SUPABASE_URL)
    # Pinned explicitly, not delenv'd: Settings reads backend/.env directly
    # (env_file=".env"), so on a dev machine with AUTH_REQUIRED=true actually
    # set there, delenv'ing the OS var wouldn't hide it — same class of bug
    # documented in test_jwt_verifier.py's test_no_supabase_url_configured_raises.
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_token(**extra_claims):
    now = int(time.time())
    payload = {
        "sub": "user-123",
        "aud": "authenticated",
        "iss": _ISSUER,
        "iat": now,
        "exp": now + 3600,
        **extra_claims,
    }
    return jwt.encode(payload, _SECRET, algorithm="HS256")


def test_returns_none_for_a_missing_header_when_auth_is_not_required():
    assert get_current_user(authorization=None) is None


def test_returns_none_for_a_malformed_header_when_auth_is_not_required():
    assert get_current_user(authorization="not-a-bearer-token") is None
    assert get_current_user(authorization="Bearer") is None


def test_returns_none_for_an_invalid_token_when_auth_is_not_required():
    assert get_current_user(authorization="Bearer garbage.not.a.jwt") is None


def test_returns_the_real_user_for_a_valid_token_even_when_auth_is_not_required():
    """A *valid* token is always honored, regardless of AUTH_REQUIRED — that
    flag only governs what happens to callers with no/a bad token, never
    whether a good one is trusted."""
    token = _make_token(email="person@example.com")

    user = get_current_user(authorization=f"Bearer {token}")

    assert user is not None
    assert user.id == "user-123"
    assert user.email == "person@example.com"
    assert user.is_anonymous is False


def test_bearer_scheme_is_case_insensitive():
    token = _make_token()
    user = get_current_user(authorization=f"bearer {token}")
    assert user is not None
    assert user.id == "user-123"


def test_raises_401_for_a_missing_header_when_auth_is_required(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=None)
    assert exc_info.value.status_code == 401


def test_raises_401_for_an_invalid_token_when_auth_is_required(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization="Bearer garbage.not.a.jwt")
    assert exc_info.value.status_code == 401


def test_still_returns_the_real_user_for_a_valid_token_when_auth_is_required(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    token = _make_token()

    user = get_current_user(authorization=f"Bearer {token}")

    assert user is not None
    assert user.id == "user-123"

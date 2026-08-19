"""Shared fixtures for every `test_api/` module — moved out of
`test_routes.py` (their original home) so `test_finalize_route.py` and any
future `test_api/` module get them without duplicating the definitions.
"""

from __future__ import annotations

import pytest

from src.config import get_settings


@pytest.fixture(autouse=True)
def _auth_not_required_by_default(monkeypatch):
    """Pin AUTH_REQUIRED=false for this directory's baseline, explicitly
    rather than relying on config.py's default: Settings reads backend/.env
    directly (env_file=".env"), so on a dev machine that has since flipped
    AUTH_REQUIRED=true there for real, an un-pinned test would silently
    inherit that and 401 on every request below that sends no token —
    same class of bug already documented in test_jwt_verifier.py's
    test_no_supabase_url_configured_raises. Most tests here exercise
    business logic (session lifecycle, hotel flows, planner turns) that is
    orthogonal to the auth rollout flag; the handful that specifically test
    ownership/AUTH_REQUIRED behavior use the auth_override fixture below or
    set the env var themselves.
    """
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def auth_override():
    """Overrides the get_current_user dependency for the app under test.

    Call with a user id to simulate an authenticated caller, or with None to
    simulate no/an invalid token (AUTH_REQUIRED defaults to False, so that is
    "anonymous", not "rejected" — see src/auth/dependencies.py). Always
    cleared after the test, pass or fail.
    """
    from src.auth import AuthenticatedUser, get_current_user
    from src.main import app

    def _set(user_id: str | None):
        if user_id is None:
            app.dependency_overrides.pop(get_current_user, None)
            return
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            id=user_id, email=f"{user_id}@example.com", is_anonymous=False
        )

    yield _set
    app.dependency_overrides.pop(get_current_user, None)

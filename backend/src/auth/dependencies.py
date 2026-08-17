"""FastAPI dependency exposing the caller's identity to route handlers.

Rollout behavior (mirrors the existing SESSION_PERSISTENCE_ENABLED pattern in
src/config.py — ship the machinery, flip a flag once the other side of the
wire is confirmed ready):

- Authorization header present and the token verifies: always returns the
  real AuthenticatedUser, regardless of AUTH_REQUIRED. A valid caller is
  always identified.
- Header missing, or present but fails verification, AND settings.auth_required
  is False (the default during rollout — see backend/.env.example): returns
  None rather than raising. Existing tests/clients that send no Authorization
  header at all keep working unmodified.
- Same failure, AND settings.auth_required is True: raises 401.

`current_user: AuthenticatedUser | None` reaching a route handler as None is
NOT the same as "grant access to everything" — see
src.api.routes._owned_session_or_404 and list_persisted_sessions for how each
call site treats the no-identity case (existence-only checks stay permissive
during rollout; the GET /chat/sessions aggregate list — the one endpoint with
no legitimate unauthenticated use — returns empty rather than leaking every
caller's rows regardless of AUTH_REQUIRED).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException

from src.auth.jwt_verifier import TokenVerificationError, verify_access_token
from src.config import get_settings

_UNAUTHENTICATED_DETAIL = "Chưa đăng nhập hoặc phiên đăng nhập không hợp lệ."


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str | None
    is_anonymous: bool


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def get_current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser | None:
    token = _extract_bearer_token(authorization)
    try:
        if not token:
            raise TokenVerificationError("Missing session token.")
        claims = verify_access_token(token)
    except TokenVerificationError:
        if get_settings().auth_required:
            raise HTTPException(status_code=401, detail=_UNAUTHENTICATED_DETAIL) from None
        return None
    return AuthenticatedUser(id=claims.user_id, email=claims.email, is_anonymous=claims.is_anonymous)

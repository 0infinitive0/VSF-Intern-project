"""Authorization for the admin API — deliberately separate from
src.auth.dependencies.get_current_user.

get_current_user returns None (rather than raising) whenever a token is
missing/invalid AND settings.auth_required is False, to support the guest
chat app's permissive rollout. Admin endpoints must never inherit that
behavior: an admin route with no/invalid credentials always 401s, and one
with a non-admin caller always 403s, regardless of AUTH_REQUIRED. Keeping
this in its own module (not added onto dependencies.py) keeps that
"permissive rollout" vs "always strict" boundary visible at a glance.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException

from src.auth.dependencies import extract_bearer_token
from src.auth.jwt_verifier import TokenVerificationError, verify_access_token

ADMIN_ROLE = "admin"


@dataclass(frozen=True)
class AdminUser:
    id: str
    email: str | None


def require_admin(authorization: str | None = Header(default=None)) -> AdminUser:
    token = extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập.")
    try:
        claims = verify_access_token(token)
    except TokenVerificationError:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập không hợp lệ.") from None
    if claims.is_anonymous or claims.app_role != ADMIN_ROLE:
        raise HTTPException(
            status_code=403, detail="Tài khoản này không có quyền truy cập trang quản trị."
        )
    return AdminUser(id=claims.user_id, email=claims.email)

"""Supabase JWT verification and per-request auth (plan 260814-supabase-auth-and-per-user-history).

Every visitor — anonymous or permanent — carries a real Supabase-issued JWT
(Supabase Anonymous Auth is used for guests, see docs/chat_api_contract.md).
This package verifies that JWT locally on every request (no per-request call
to the Supabase Auth API, see jwt_verifier.py's module docstring for why) and
exposes the resulting identity to route handlers via `get_current_user`.

The admin API uses a separate, always-strict dependency, `require_admin` (see
admin.py's module docstring for why it is not folded into `get_current_user`).
"""

from src.auth.admin import AdminUser, require_admin
from src.auth.dependencies import AuthenticatedUser, get_current_user

__all__ = ["AdminUser", "AuthenticatedUser", "get_current_user", "require_admin"]

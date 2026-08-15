"""Supabase JWT verification and per-request auth (plan 260814-supabase-auth-and-per-user-history).

Every visitor — anonymous or permanent — carries a real Supabase-issued JWT
(Supabase Anonymous Auth is used for guests, see docs/chat_api_contract.md).
This package verifies that JWT locally on every request (no per-request call
to the Supabase Auth API, see jwt_verifier.py's module docstring for why) and
exposes the resulting identity to route handlers via `get_current_user`.
"""

from src.auth.dependencies import AuthenticatedUser, get_current_user

__all__ = ["AuthenticatedUser", "get_current_user"]

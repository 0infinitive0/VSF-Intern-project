"""Writes rows to admin_audit_log for every admin-side write action."""

from __future__ import annotations

import logging

from src.auth import AdminUser
from src.clients.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def write_audit(
    actor: AdminUser,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    """Records one admin action. Never raises: a failed audit write must not
    fail an admin action that already succeeded against real booking/payment
    data."""
    try:
        get_supabase_client().table("admin_audit_log").insert(
            {
                "actor_id": actor.id,
                "actor_email": actor.email,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "before": before,
                "after": after,
            }
        ).execute()
    except Exception:
        logger.exception(
            "Failed to write admin_audit_log row for action=%s entity_type=%s entity_id=%s",
            action,
            entity_type,
            entity_id,
        )

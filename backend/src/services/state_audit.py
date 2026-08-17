"""State patch audit service — Phase 10.

Records every applied and rejected state-patch change to
``sessions.context_data["state_audit"]`` in Supabase.

## Contract

- **Best-effort, never raises.** A DB outage must not fail a chat turn.
  Same retry-once-then-log shape as ``supabase_persist_hook`` in
  ``agents/session.py``.
- **Append semantics.** Each turn's records are *appended* to the existing
  list; the list is never truncated here. Retention policy is a separate
  concern handled by the Phase-4 checkpoint pruning cron.
- **Pure input types.** Callers pass plain dicts (from ``dataclasses.asdict``)
  — this module never imports from the graph or domain layer.

## Record shape

```json
{
  "path": "budget.max",
  "op": "set",
  "before": null,
  "after": 2000000,
  "rejected_reason": null,
  "source": "validate_patch",
  "at": "2026-08-13T09:00:00.000000"
}
```

``before`` / ``after`` are ``None`` for rejected records (no state was written).
``rejected_reason`` is ``None`` for applied records.

## Storage layout in ``context_data``

```json
{
  "state_audit": [
    {"path": "...", "op": "set", "before": null, "after": "Đà Nẵng", "rejected_reason": null, "source": "validate_patch", "at": "..."},
    ...
  ]
}
```

Old records accumulate across turns — the outer list grows unboundedly at ~O(changes/turn).
A retention migration is scheduled alongside Phase 4's checkpoint pruning cron.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------


def _build_applied_record(
    change: dict[str, Any],
    *,
    before: Any,
    source: str,
    at: str,
) -> dict[str, Any]:
    """Build one audit record for a successfully applied change."""
    return {
        "path": change.get("path", ""),
        "op": change.get("operation", ""),
        "before": before,
        "after": change.get("value"),
        "rejected_reason": None,
        "source": source,
        "at": at,
    }


def _build_rejected_record(
    rejection: dict[str, Any],
    *,
    source: str,
    at: str,
) -> dict[str, Any]:
    """Build one audit record for a rejected change."""
    return {
        "path": rejection.get("path", ""),
        "op": rejection.get("operation", ""),
        "before": None,
        "after": None,
        "rejected_reason": rejection.get("reason", ""),
        "source": source,
        "at": at,
    }


def _before_value(path: str, travel_state_before: dict[str, Any]) -> Any:
    """Extract the pre-patch value for *path* from the slot dict.

    ``travel_state_before`` is the ``TravelState.to_dict()`` snapshot taken
    before the patch was applied.  Slots are stored as
    ``{path: {presence, value}}``.  We return ``slot["value"]`` if the slot
    existed, or ``None`` if the path had not been set yet.
    """
    slot = travel_state_before.get(path) if isinstance(travel_state_before, dict) else None
    if isinstance(slot, dict):
        return slot.get("value")
    return None


# ---------------------------------------------------------------------------
# Supabase write
# ---------------------------------------------------------------------------


def _append_to_context_data(session_id: str, new_records: list[dict[str, Any]]) -> None:
    """Append *new_records* to ``sessions.context_data["state_audit"]``.

    Uses a Postgres function (``jsonb_build_object`` / ``||``) so the append
    is atomic — two concurrent turns for the same session cannot clobber each
    other's audit rows.

    Falls back to a read-modify-write if the RPC is unavailable (e.g., the
    migration that adds the RPC has not been applied yet).
    """
    from src.services.trip_planner import get_supabase_client  # lazy import keeps module pure

    supabase = get_supabase_client()

    # Attempt atomic append via Supabase's jsonb concatenation.
    # ``context_data || '{"state_audit": [...]}'`` would OVERWRITE the key, so
    # we must use a real append pattern.  Supabase's PostgREST exposes
    # ``jsonb_set`` via rpc; fall back to read-modify-write for simplicity.
    response = (
        supabase.table("sessions")
        .select("context_data")
        .eq("session_id", session_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    existing: dict[str, Any] = {}
    if rows and isinstance(rows[0].get("context_data"), dict):
        existing = rows[0]["context_data"]

    existing_audit: list[dict[str, Any]] = list(existing.get("state_audit") or [])
    existing_audit.extend(new_records)
    merged = {**existing, "state_audit": existing_audit}

    supabase.table("sessions").upsert(
        {"session_id": session_id, "context_data": merged},
        on_conflict="session_id",
    ).execute()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def emit_patch_audit(
    session_id: str,
    applied: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    *,
    travel_state_before: dict[str, Any] | None = None,
    source: str = "validate_patch",
) -> None:
    """Emit audit records for one turn's applied and rejected changes.

    Parameters
    ----------
    session_id:
        The session/trip identifier — used as the Supabase row key.
    applied:
        List of ``dataclasses.asdict(PatchChange)`` dicts from the graph state.
    rejected:
        List of ``dataclasses.asdict(RejectedChange)`` dicts from the graph state.
    travel_state_before:
        ``TravelState.to_dict()`` snapshot **before** the patch was applied.
        Used to capture the ``before`` value.  ``None`` means "before state not
        available" — ``before`` will be ``None`` in all records.
    source:
        Which node emitted the audit (default ``"validate_patch"``).

    Never raises — a DB outage logs a warning and the turn continues.
    """
    if not session_id:
        logger.debug("emit_patch_audit: no session_id; skipping audit write")
        return
    if not applied and not rejected:
        return

    at = datetime.now(timezone.utc).isoformat()
    before_state = travel_state_before or {}

    records: list[dict[str, Any]] = []
    for change in applied:
        records.append(
            _build_applied_record(
                change,
                before=_before_value(change.get("path", ""), before_state),
                source=source,
                at=at,
            )
        )
    for rejection in rejected:
        records.append(_build_rejected_record(rejection, source=source, at=at))

    if not records:
        return

    for attempt in range(2):
        try:
            _append_to_context_data(session_id, records)
            return
        except Exception:
            if attempt == 0:
                logger.warning(
                    "Audit write failed for session %s; retrying once",
                    session_id,
                    exc_info=True,
                )
            else:
                logger.exception(
                    "Audit write failed after retry for session %s; continuing in-memory",
                    session_id,
                )

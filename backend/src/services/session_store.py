"""Optional Supabase persistence for serializable chat-session business state."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from langchain_core.messages import messages_from_dict, messages_to_dict
from supabase import Client, create_client

from src.agents.state import TripState, initial_state
from src.config import get_settings

if TYPE_CHECKING:
    from src.agents.session import TripSession

_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _get_supabase_client() -> Client:
    settings = get_settings()
    url = getattr(settings, "supabase_url", None) or os.environ.get("SUPABASE_URL")
    key = getattr(settings, "supabase_service_key", None) or os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in environment or settings.")
    return create_client(url, key)


def _require_safe_session_id(session_id: str) -> None:
    if not _SAFE_SESSION_ID.fullmatch(session_id):
        raise ValueError("Unsafe session id for persistent storage.")


def serialize(session: TripSession) -> dict[str, Any]:
    """JSON-safe business state, excluding LangGraph's runtime-only key."""
    state = dict(session.state)
    messages = state.pop("messages", [])
    state.pop("remaining_steps", None)
    return {**state, "messages": messages_to_dict(messages)}


def deserialize(session_id: str, context_data: dict[str, Any] | None) -> TripState:
    """Rebuild only the serializable TripState; runtime fields are rebuilt elsewhere."""
    state = initial_state(session_id)
    context = context_data or {}
    for key in state:
        if key not in {"messages", "remaining_steps"} and key in context:
            state[key] = context[key]
    state["messages"] = messages_from_dict(context.get("messages") or [])
    return state


def upsert(session: TripSession) -> None:
    _require_safe_session_id(session.session_id)
    _get_supabase_client().table("sessions").upsert(
        {
            "session_id": session.session_id,
            "context_data": serialize(session),
            "updated_at": datetime.now(UTC).isoformat(),
        },
        on_conflict="session_id",
    ).execute()


def load(session_id: str) -> dict[str, Any] | None:
    _require_safe_session_id(session_id)
    rows = (
        _get_supabase_client().table("sessions").select("session_id,context_data,created_at,updated_at")
        .eq("session_id", session_id).limit(1).execute().data or []
    )
    return dict(rows[0]) if rows else None


def delete(session_id: str) -> None:
    _require_safe_session_id(session_id)
    _get_supabase_client().table("sessions").delete().eq("session_id", session_id).execute()


def list_sessions(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 100))
    return (
        _get_supabase_client().table("sessions").select("session_id,context_data,created_at,updated_at")
        .order("updated_at", desc=True).limit(safe_limit).execute().data or []
    )


def restored_messages(context_data: dict[str, Any] | None) -> list[dict[str, str]]:
    messages = messages_from_dict((context_data or {}).get("messages") or [])
    restored = []
    for message in messages:
        role = "assistant" if message.type == "ai" else "user"
        metadata = getattr(message, "additional_kwargs", {}) or {}
        content = message.content
        restored.append(
            {
                "role": role,
                "text": content if isinstance(content, str) else str(content),
                "stage": str(metadata.get("stage") or "intake"),
                "at": str(metadata.get("at") or ""),
            }
        )
    return restored


def summarize(row: dict[str, Any]) -> dict[str, Any]:
    context = row.get("context_data") or {}
    intake = context.get("intake") or {}
    trip_data = context.get("trip_data") or {}
    hotel = trip_data.get("hotel") or {}
    messages = restored_messages(context)
    first_user_text = next((item["text"] for item in messages if item["role"] == "user"), None)
    duration_days = trip_data.get("duration_days")
    if duration_days is None:
        itineraries = trip_data.get("itineraries") or []
        duration_days = itineraries[0].get("duration_days") if itineraries else None
    return {
        "session_id": str(row["session_id"]),
        "title": first_user_text[:120] if first_user_text else None,
        "destination": intake.get("destination") or trip_data.get("destination"),
        "duration_days": duration_days,
        "status": "completed" if trip_data else "draft",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "thumbnail_url": hotel.get("image_url"),
    }

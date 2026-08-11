"""Persistence helpers for compact planner checkpoints and chat transcripts."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Iterable

from langchain_core.messages import AIMessage, HumanMessage, messages_from_dict, messages_to_dict
from postgrest.exceptions import APIError
from supabase import Client, create_client

from src.agents.state import TripState, initial_state
from src.config import get_settings

if TYPE_CHECKING:
    from src.agents.session import TripSession

_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_CONTEXT_SCHEMA_VERSION = 2
_CHECKPOINT_FIELDS = (
    "intake",
    "hotel_prefs",
    "language",
    "initial_plan_complete",
    "planning_new_trip",
    "pending_hotel_selection",
    "pending_trip_edit_request",
    "pending_trip_preference_request",
    "preference_replacement_state",
    "pending_parameter_confirmation",
)
_PENDING_HOTEL_FIELDS = (
    "mode",
    "destination",
    "destination_id",
    "duration",
    "people",
    "preferences_text",
    "hotel_query",
    "start_date",
    "end_date",
    "planning_constraints",
    "compound_min_price",
    "compound_max_price",
    "all_preferences",
    "active_preferences",
)
_HOTEL_SNAPSHOT_FIELDS = (
    "id",
    "hotel_id",
    "name",
    "star_rating",
    "description",
    "average_nightly_price",
    "total_stay_price",
    "stay_night_count",
    "currency",
    "coordinates",
    "latitude",
    "longitude",
    "address",
    "area_name",
    "image_url",
    "amenities",
    "review_score",
    "review_count",
    "match_score",
    "match_reasons",
    "city",
    "preferences",
    "matched_room_names",
)


@dataclass(frozen=True)
class SessionPage:
    rows: list[dict[str, Any]]
    page: int
    page_size: int
    has_more: bool


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


def _current_trip(state: dict[str, Any]) -> dict[str, Any]:
    trip_data = state.get("trip_data") or {}
    itinerary = next(iter(trip_data.get("itineraries") or []), {})
    hotel = trip_data.get("hotel") or {}
    return {
        "itinerary_id": itinerary.get("id"),
        "hotel_id": itinerary.get("hotel_id") or hotel.get("id"),
        "status": itinerary.get("status"),
    }


def _ui_summary(state: dict[str, Any], current_trip: dict[str, Any]) -> dict[str, Any]:
    intake = state.get("intake") or {}
    trip_data = state.get("trip_data") or {}
    hotel = trip_data.get("hotel") or {}
    itinerary = next(iter(trip_data.get("itineraries") or []), {})
    is_finalized = str(current_trip.get("status") or "").casefold() == "finalized"
    return {
        "destination": intake.get("destination") or trip_data.get("destination"),
        "duration_days": itinerary.get("duration_days") or trip_data.get("duration_days"),
        "status": "completed" if is_finalized else "draft",
        "hotel_name": hotel.get("name"),
        "thumbnail_url": hotel.get("image_url"),
    }


def _pending_hotel_checkpoint(pending: Any) -> dict[str, Any] | None:
    if not isinstance(pending, dict):
        return None
    checkpoint = {field: pending.get(field) for field in _PENDING_HOTEL_FIELDS if field in pending}
    snapshots = []
    for option in pending.get("options") or []:
        if not isinstance(option, dict) or not (option.get("id") or option.get("hotel_id")):
            continue
        snapshots.append({field: option.get(field) for field in _HOTEL_SNAPSHOT_FIELDS if field in option})
    checkpoint["option_ids"] = [str(option.get("id") or option.get("hotel_id")) for option in snapshots]
    checkpoint["options"] = snapshots
    return checkpoint


def serialize(session: TripSession) -> dict[str, Any]:
    """Create the v2 checkpoint without transcript, raw plan, or runtime fields."""
    state = dict(session.state)
    current_trip = _current_trip(state)
    workflow = {field: state.get(field) for field in _CHECKPOINT_FIELDS if field != "pending_hotel_selection"}
    workflow["pending_hotel_selection"] = _pending_hotel_checkpoint(state.get("pending_hotel_selection"))
    return {
        "schema_version": _CONTEXT_SCHEMA_VERSION,
        "workflow": workflow,
        "current_trip": current_trip,
        "ui_summary": _ui_summary(state, current_trip),
    }


def _deserialize_v1(session_id: str, context: dict[str, Any]) -> TripState:
    state = initial_state(session_id)
    for key in state:
        if key not in {"messages", "remaining_steps"} and key in context:
            state[key] = context[key]
    state["messages"] = messages_from_dict(context.get("messages") or [])
    return state


def _messages_from_rows(rows: Iterable[dict[str, Any]]) -> list[HumanMessage | AIMessage]:
    restored: list[HumanMessage | AIMessage] = []
    for row in rows:
        role = str(row.get("sender_type") or "user")
        metadata = {
            "stage": "intake",
            "at": str(row.get("created_at") or ""),
        }
        message_type = AIMessage if role == "assistant" else HumanMessage
        restored.append(message_type(content=str(row.get("message_content") or ""), additional_kwargs=metadata))
    return restored


def deserialize(
    session_id: str,
    context_data: dict[str, Any] | None,
    message_rows: Iterable[dict[str, Any]] | None = None,
) -> TripState:
    """Rebuild checkpoint state; v1 contexts remain readable until next save."""
    context = context_data or {}
    if context.get("schema_version") != _CONTEXT_SCHEMA_VERSION:
        state = _deserialize_v1(session_id, context)
    else:
        state = initial_state(session_id)
        workflow = context.get("workflow") or {}
        for field in _CHECKPOINT_FIELDS:
            if field in workflow:
                state[field] = workflow[field]
    if message_rows is not None:
        state["messages"] = _messages_from_rows(message_rows)
    return state


def _message_records(session: TripSession) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for message in session.state.get("messages") or []:
        metadata = getattr(message, "additional_kwargs", {}) or {}
        content = message.content
        records.append(
            {
                "sender_type": "assistant" if message.type == "ai" else "user",
                "message_content": content if isinstance(content, str) else str(content),
                "created_at": str(metadata.get("at") or datetime.now(UTC).isoformat()),
            }
        )
    return records


def upsert(session: TripSession) -> None:
    """Atomically save the checkpoint and transcript; the RPC is retry-idempotent."""
    _require_safe_session_id(session.session_id)
    client = _get_supabase_client()
    checkpoint = serialize(session)
    messages = _message_records(session)
    try:
        client.rpc(
            "persist_session_checkpoint",
            {
                "p_session_id": session.session_id,
                "p_context_data": checkpoint,
                "p_messages": messages,
            },
        ).execute()
        return
    except APIError as exc:
        # Keep persistence available while an older environment is waiting for
        # the migration that creates the transactional RPC.  Other database
        # errors remain visible to the session hook and retain its retry path.
        if exc.code != "PGRST202" or "persist_session_checkpoint" not in str(exc):
            raise

    client.table("sessions").upsert(
        {"session_id": session.session_id, "context_data": checkpoint},
        on_conflict="session_id",
    ).execute()
    client.table("chat_messages").delete().eq("session_id", session.session_id).execute()
    if messages:
        client.table("chat_messages").insert(
            [{"session_id": session.session_id, **message} for message in messages]
        ).execute()


def load(session_id: str) -> dict[str, Any] | None:
    _require_safe_session_id(session_id)
    client = _get_supabase_client()
    rows = (
        client.table("sessions").select("session_id,context_data,created_at,updated_at")
        .eq("session_id", session_id).limit(1).execute().data or []
    )
    if not rows:
        return None
    row = dict(rows[0])
    row["messages"] = (
        client.table("chat_messages")
        .select("sender_type,message_content,created_at")
        .eq("session_id", session_id)
        .order("created_at")
        .execute().data or []
    )
    return row


def delete(session_id: str) -> None:
    _require_safe_session_id(session_id)
    _get_supabase_client().table("sessions").delete().eq("session_id", session_id).execute()


def list_sessions(page: int = 1, page_size: int = 10) -> SessionPage:
    safe_page = max(1, page)
    safe_page_size = max(1, min(page_size, 100))
    start = (safe_page - 1) * safe_page_size
    rows = (
        _get_supabase_client().table("sessions").select("session_id,context_data,created_at,updated_at")
        .order("updated_at", desc=True).order("session_id", desc=True)
        .range(start, start + safe_page_size).execute().data or []
    )
    return SessionPage(
        rows=[dict(row) for row in rows[:safe_page_size]],
        page=safe_page,
        page_size=safe_page_size,
        has_more=len(rows) > safe_page_size,
    )


def restored_messages(source: dict[str, Any] | Iterable[Any] | None) -> list[dict[str, str]]:
    if isinstance(source, dict):
        messages = messages_from_dict(source.get("messages") or [])
    else:
        messages = list(source or [])
    restored = []
    for message in messages:
        if isinstance(message, dict):
            role = "assistant" if message.get("sender_type") == "assistant" else "user"
            restored.append(
                {
                    "role": role,
                    "text": str(message.get("message_content") or ""),
                    "stage": str(message.get("stage") or "intake"),
                    "at": str(message.get("created_at") or ""),
                }
            )
            continue
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
    if context.get("schema_version") == _CONTEXT_SCHEMA_VERSION:
        summary = context.get("ui_summary") or {}
        # Legacy rows may carry the itinerary vocabulary ("Draft"/"Finalized")
        # instead of the UI vocabulary ("draft"/"completed") — normalize so
        # SessionSummaryPayload's Literal validation never rejects a row.
        raw_status = str(summary.get("status") or "").casefold()
        status = "completed" if raw_status in ("completed", "finalized") else "draft"
        return {
            "session_id": str(row["session_id"]),
            "title": None,
            "destination": summary.get("destination"),
            "duration_days": summary.get("duration_days"),
            "status": status,
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "thumbnail_url": summary.get("thumbnail_url"),
        }
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

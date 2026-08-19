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

from src.config import get_settings

if TYPE_CHECKING:
    from src.agents.session import TripSession

_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_CONTEXT_SCHEMA_VERSION = 2
#: The graph plane's own `context_data` shape. Sourced from `TravelGraphState`
#: rather than the `TripSession.state` mirror v2 describes, so it carries none
#: of that plane's vocabulary (`workflow`, `pending_hotel_selection`). Only
#: `persist_graph_session` writes it; `upsert` still writes v2 for the CLI.
_CONTEXT_SCHEMA_VERSION_V3 = 3
#: Tag `respond` puts on the one AI message per turn the user actually sees
#: (`agents/graph/nodes/respond.py`). Everything else in the `messages`
#: channel is a ReAct agent's working notes.
_EMITTED_BY_RESPOND = "respond"
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


def _travel_state_destination(travel_state: dict[str, Any] | None) -> str | None:
    """The destination slot, read through the domain type rather than by
    poking at the serialized `{presence, value}` shape — one place owns what
    "answered" means (`Presence.SET`, not merely "a key exists")."""
    from src.domain.travel_state import Presence, TravelState

    slot = TravelState.from_dict(travel_state or {}).get("destination")
    return slot.value if slot.presence is Presence.SET else None


def _v3_context(state: dict[str, Any]) -> dict[str, Any]:
    """Build the v3 checkpoint from graph state.

    `travel_state` is the business truth, stored verbatim — it is already the
    flat, JSON-safe `TravelState.to_dict()` shape. `trip` is a pointer to rows
    that live in other tables, never a copy of them. `ui_summary` keeps v2's
    exact shape on purpose: it is what `summarize()` renders into the history
    rail, it carries no dead-plane vocabulary, and keeping it means `summarize`
    only had to widen its version check instead of growing a third branch.
    """
    trip = _current_trip(state)
    # `_ui_summary` reads `intake.destination` and `trip_data` — the former is
    # a TripSession-ism with no counterpart in graph state, so it gets the
    # destination slot instead. Reusing the function rather than re-deriving
    # the summary keeps one definition of what the rail shows.
    ui_view = {
        "intake": {"destination": _travel_state_destination(state.get("travel_state"))},
        "trip_data": state.get("trip_data"),
    }
    return {
        "schema_version": _CONTEXT_SCHEMA_VERSION_V3,
        "travel_state": state.get("travel_state") or {},
        "trip": trip,
        "ui_summary": _ui_summary(ui_view, trip),
    }


def _graph_message_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The conversation as the user saw it, out of the graph's message channel.

    `messages` also carries `qa_node`'s ReAct scratchpad — tool calls, tool
    results, and the sub-agent's own draft answer. Filtering by `respond`'s
    tag rather than by message type is what separates the two: `respond` is
    the only node that produces a reply, so its tag is an exact description of
    "what was shown", not a heuristic about what looks like prose.
    """
    records: list[dict[str, Any]] = []
    for message in state.get("messages") or []:
        message_type = getattr(message, "type", None)
        metadata = getattr(message, "additional_kwargs", None) or {}
        if message_type == "ai":
            if metadata.get("emitted_by") != _EMITTED_BY_RESPOND:
                continue
            sender = "assistant"
        elif message_type == "human":
            sender = "user"
        else:
            continue  # tool results and anything else the graph adds later
        content = getattr(message, "content", "")
        records.append(
            {
                "sender_type": sender,
                "message_content": content if isinstance(content, str) else str(content),
                # Each message carries the moment it was created (stamped where
                # it is built). Every write re-sends the whole transcript, so
                # stamping "now" here would move every past message to the
                # current instant and flatten the ordering `load()` sorts by.
                "created_at": str(metadata.get("at") or datetime.now(UTC).isoformat()),
            }
        )
    return records


def persist_graph_session(session: TripSession, state: dict[str, Any]) -> None:
    """Write one graph turn's session row and transcript.

    Replaces the `persist_hook` -> `upsert(TripSession)` path the graph cutover
    removed. `session` supplies only identity and ownership; every byte of
    content comes from `state`, so `TripSession.state` stays unused by the HTTP
    plane (it now serves the CLI alone).
    """
    _require_safe_session_id(session.session_id)
    _write_checkpoint(
        session_id=session.session_id,
        owner_user_id=session.owner_user_id,
        checkpoint=_v3_context(state),
        messages=_graph_message_records(state),
    )


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


def _deserialize_v1(context: dict[str, Any]) -> dict[str, Any]:
    """Restore a pre-v2 checkpoint, which stored its fields flat at the top
    level of ``context_data`` instead of under ``workflow``.

    The field list is `_CHECKPOINT_FIELDS` — the same durable set v2 restores
    — so an old row rehydrates the same workflow state a new one does.
    ``messages`` is rebuilt separately below; runtime-only keys are not
    restored at all."""
    state: dict[str, Any] = {field: context[field] for field in _CHECKPOINT_FIELDS if field in context}
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
) -> dict[str, Any]:
    """Rebuild checkpoint state; v1 contexts remain readable until next save."""
    context = context_data or {}
    version = context.get("schema_version")
    if version == _CONTEXT_SCHEMA_VERSION_V3:
        # A v3 row describes graph state, which lives in the checkpointer and
        # is never rebuilt into `TripSession.state`. Blocked explicitly rather
        # than left to fall through: `_deserialize_v1` copies any top-level key
        # matching `_CHECKPOINT_FIELDS`, so a future v3 key that happens to
        # share one of those names would silently become legacy workflow state.
        state = {}
    elif version != _CONTEXT_SCHEMA_VERSION:
        state = _deserialize_v1(context)
    else:
        state = {}
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
    """Atomically save the checkpoint and transcript; the RPC is retry-idempotent.

    Writes the v2 shape from `TripSession.state`. The HTTP plane no longer
    reaches this — it runs `persist_graph_session` instead — but the CLI
    (`src/cli/terminal_chat.py`) still owns a real `TripSession`, so this stays.
    """
    _require_safe_session_id(session.session_id)
    _write_checkpoint(
        session_id=session.session_id,
        owner_user_id=session.owner_user_id,
        checkpoint=serialize(session),
        messages=_message_records(session),
    )


def _write_checkpoint(
    *,
    session_id: str,
    owner_user_id: str | None,
    checkpoint: dict[str, Any],
    messages: list[dict[str, Any]],
) -> None:
    """The one write path both checkpoint shapes go through — the RPC, its
    pre-migration fallback, and the ownership stamp. Shared so the v2 and v3
    writers cannot drift apart on retry semantics or on which tables they
    touch."""
    client = _get_supabase_client()
    try:
        client.rpc(
            "persist_session_checkpoint",
            {
                "p_session_id": session_id,
                "p_context_data": checkpoint,
                "p_messages": messages,
            },
        ).execute()
        _stamp_owner(client, session_id, owner_user_id)
        return
    except APIError as exc:
        # Keep persistence available while an older environment is waiting for
        # the migration that creates the transactional RPC.  Other database
        # errors remain visible to the session hook and retain its retry path.
        if exc.code != "PGRST202" or "persist_session_checkpoint" not in str(exc):
            raise

    client.table("sessions").upsert(
        {"session_id": session_id, "context_data": checkpoint, "user_id": owner_user_id},
        on_conflict="session_id",
    ).execute()
    client.table("chat_messages").delete().eq("session_id", session_id).execute()
    if messages:
        client.table("chat_messages").insert(
            [{"session_id": session_id, **message} for message in messages]
        ).execute()


def _stamp_owner(client: Client, session_id: str, owner_user_id: str | None) -> None:
    """Set `sessions.user_id` after a checkpoint write.

    Separate from the RPC call above on purpose: `persist_session_checkpoint`'s
    defining migration (20260811_add_session_checkpoint_persistence.sql) isn't
    tracked in this repo (see backend/tests/test_session_store.py — that test
    already fails independent of this change), so its live body/params aren't
    knowable here. Stamping ownership as its own small update works regardless
    of what that RPC does internally, and is idempotent — an anonymous
    session's user_id never actually changes across writes to the same row
    (Supabase's anonymous->permanent upgrade keeps the same auth.users.id), so
    this is a no-op on every write after the first for a given session.
    """
    if owner_user_id is None:
        return
    client.table("sessions").update({"user_id": owner_user_id}).eq(
        "session_id", session_id
    ).execute()


def load(session_id: str) -> dict[str, Any] | None:
    _require_safe_session_id(session_id)
    client = _get_supabase_client()
    rows = (
        client.table("sessions").select("session_id,context_data,user_id,created_at,updated_at")
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


def delete(session_id: str, *, user_id: str | None = None) -> None:
    """Delete a persisted session row.

    `user_id` is an optional second, DB-level safety net behind the route-level
    ownership check in src.api.routes (_owned_session_or_404) — not load-bearing
    on its own (the route never calls this for a session it has already
    determined belongs to someone else), but cheap insurance on a destructive
    operation. None (the default) preserves today's unscoped behavior, used by
    SessionRegistry's delete_hook wiring, which only ever calls this after its
    own caller has already checked ownership.
    """
    _require_safe_session_id(session_id)
    query = _get_supabase_client().table("sessions").delete().eq("session_id", session_id)
    if user_id is not None:
        query = query.eq("user_id", user_id)
    query.execute()


def booking_states_for_sessions(session_ids: list[str]) -> dict[str, str]:
    """One extra query per page of GET /chat/sessions rows -> {session_id:
    'paid'|'holding'} — the sidebar "Đang giữ phòng"/"Đã thanh toán" badge
    (plan 260818-vnpay-payment-and-email-confirmation's addendum 2).
    bookings.status='CONFIRMED' already reliably means "paid" in this app:
    confirm_booking_reservation is only ever called from the VNPay IPN
    handler (routes.py's vnpay_ipn) after a real payment succeeds, so no
    separate join to `payments` is needed.

    Deliberately does NOT push the RESERVED-and-unexpired filter into the
    query as a raw `now()` comparison via postgrest's string `.or_()`
    filters (no precedent for that in this codebase) — pulls every
    CONFIRMED/RESERVED row for the page's sessions and filters expiry here
    instead, same idea as routes.py's create_vnpay_payment already does for
    a single booking's expires_at. Page sizes are small (<=100 sessions,
    normally far fewer bookings each), so this stays one cheap query.

    Precedence (paid beats holding for the same session_id) is applied
    here so callers never have to re-derive it."""
    if not session_ids:
        return {}
    rows = (
        _get_supabase_client()
        .table("bookings")
        .select("session_id,status,expires_at")
        .in_("session_id", session_ids)
        .in_("status", ["CONFIRMED", "RESERVED"])
        .execute()
        .data
        or []
    )
    now = datetime.now(UTC)
    states: dict[str, str] = {}
    for row in rows:
        session_id = row.get("session_id")
        if not session_id:
            continue
        if row.get("status") == "CONFIRMED":
            states[session_id] = "paid"
            continue
        if states.get(session_id) == "paid":
            continue
        expires_at = row.get("expires_at")
        if expires_at and datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")) > now:
            states[session_id] = "holding"
    return states


def list_sessions(user_id: str, page: int = 1, page_size: int = 10) -> SessionPage:
    """List sessions owned by `user_id` only.

    Previously took no user_id and listed every persisted session globally —
    a real privacy bug once more than one visitor exists (plan
    260814-supabase-auth-and-per-user-history). Every caller of this function
    must now resolve a real caller identity first; src.api.routes returns an
    empty page instead of calling this at all when there is none.

    `chat_messages!inner(session_id)` forces an inner join, so a session with
    zero messages (created_session() no longer persists on creation — see
    routes.py — but old rows and any other empty-session edge case still
    exist) never reaches the rail as a contentless "Chuyến đi mới" entry. A
    join on real message rows is schema-version-agnostic — it doesn't care
    whether context_data is the v1 or v2 checkpoint shape, unlike filtering
    on a parsed JSON field would. The join column is minimal (session_id
    only); it's discarded by summarize(), which never reads it.
    """
    safe_page = max(1, page)
    safe_page_size = max(1, min(page_size, 100))
    start = (safe_page - 1) * safe_page_size
    rows = (
        _get_supabase_client()
        .table("sessions")
        .select("session_id,context_data,created_at,updated_at,chat_messages!inner(session_id)")
        .eq("user_id", user_id)
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


def summarize(row: dict[str, Any], booking_state: str | None = None) -> dict[str, Any]:
    """`booking_state` ('holding'/'paid'/None) comes from
    `booking_states_for_sessions` and, when set, overrides the
    itinerary-derived draft/completed status below — see
    SessionSummaryPayload.status's doc comment for the precedence rule.
    Applied identically in both branches (a session's booking state is
    unrelated to which checkpoint schema version wrote its context_data)."""
    context = row.get("context_data") or {}
    # v2 and v3 differ in everything except this block: both carry the same
    # `ui_summary` shape, which is exactly why v3 kept it. A row written by
    # either writer renders identically in the history rail.
    if context.get("schema_version") in (_CONTEXT_SCHEMA_VERSION, _CONTEXT_SCHEMA_VERSION_V3):
        summary = context.get("ui_summary") or {}
        # Legacy rows may carry the itinerary vocabulary ("Draft"/"Finalized")
        # instead of the UI vocabulary ("draft"/"completed") — normalize so
        # SessionSummaryPayload's Literal validation never rejects a row.
        raw_status = str(summary.get("status") or "").casefold()
        status = "completed" if raw_status in ("completed", "finalized") else "draft"
        if booking_state in ("paid", "holding"):
            status = booking_state
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
    status = "completed" if trip_data else "draft"
    if booking_state in ("paid", "holding"):
        status = booking_state
    return {
        "session_id": str(row["session_id"]),
        "title": first_user_text[:120] if first_user_text else None,
        "destination": intake.get("destination") or trip_data.get("destination"),
        "duration_days": duration_days,
        "status": status,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "thumbnail_url": hotel.get("image_url"),
    }

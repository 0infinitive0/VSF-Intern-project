"""Per-session state and turn processing for the trip planner agent.

Absorbs the former `src/services/chat_session.py`: it drives `agent.stream()`,
imports the four agent-visible tool factories, and holds the compiled LangGraph
agent per session — that makes it agent orchestration, not a service. `TripSession`
replaces the two module-level JSON files with per-session fields, so two
conversations never overwrite each other's state.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from src.config import get_settings
from src.i18n import SUPPORTED_LANGUAGES
from src.services.hotel_selection import HotelPreferenceState
from src.services.trip_intake import TripIntakeState

logger = logging.getLogger(__name__)

_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

DEFAULT_SESSION_TTL_SECONDS = 2 * 60 * 60
DEFAULT_SESSION_CAP = 200


# `TurnResult`, `_STAGE_MAP` and `derive_stage` used to live here: the HTTP
# layer built a stage from whichever tool `process_chat_turn` had run. That
# cascade was deleted with the graph cutover and took every caller with it,
# leaving the trio unreachable — and `_STAGE_MAP` was the sole producer of the
# `modified`/`finalized` stages, which is why `ChatStage` kept declaring two
# values nothing could emit. Stage derivation now belongs to
# `agents/graph/response_payload.py::derive_stage`, off graph state.


class TripSession:
    """Per-conversation runtime holder — one instance per terminal run, or per
    web session_id. Wraps a serializable `TripState` (`self.state`): every
    business fact (`intake_state`, `hotel_pref_state`, `trip_data`,
    `pending_hotel_selection`, `initial_plan_complete`, `planning_new_trip`,
    `pending_trip_edit_request`) lives in `self.state` and is exposed here
    only as a property, so a checkpointer can eventually own `state` directly
    (Phase 7) without this class changing shape.

    `agent`, `tools`, `persist_hook`, `lock`, `created_at`, `last_seen_at` are
    process-local runtime fields — not serializable, not checkpointed, rebuilt
    on every process start.

    The seven business-fact properties, and this class's ability to accept
    them as constructor keyword arguments, are a TRANSITIONAL compatibility
    shim: existing call sites and tests keep working unchanged through phases
    3-5. Phase 5 removes both the properties and the constructor kwargs once
    the StateGraph itself owns `state` and nothing constructs a TripSession
    with them directly.
    """

    def __init__(
        self,
        session_id: str,
        config: dict,
        *,
        persist_hook: Callable[[TripSession], None] | None = None,
        owner_user_id: str | None = None,
        created_at: float | None = None,
        last_seen_at: float | None = None,
        lock: threading.Lock | None = None,
        state: dict[str, Any] | None = None,
        intake_state: TripIntakeState | None = None,
        hotel_pref_state: HotelPreferenceState | None = None,
        initial_plan_complete: bool | None = None,
        planning_new_trip: bool | None = None,
        pending_trip_edit_request: str | None = None,
        pending_trip_preference_request: str | None = None,
        preference_replacement_state: TripIntakeState | None = None,
        trip_data: dict[str, Any] | None = None,
        pending_hotel_selection: dict[str, Any] | None = None,
        pending_place_selection: dict[str, Any] | None = None,
    ) -> None:
        self.session_id = session_id
        self.config = config
        self.persist_hook = persist_hook
        # Real auth.users.id for every visitor once the frontend sends a
        # Supabase JWT (anonymous or permanent) — None for sessions created
        # before plan 260814 shipped, or outside the HTTP API (the CLI never
        # sets this). See src.api.routes._owned_session_or_404 for how a
        # None owner is treated (permissively, not "open to everyone").
        self.owner_user_id = owner_user_id
        self.created_at = created_at if created_at is not None else time.time()
        self.last_seen_at = last_seen_at if last_seen_at is not None else time.time()
        self.lock = lock if lock is not None else threading.Lock()
        self.state: dict[str, Any] = state if state is not None else {}

        if intake_state is not None:
            self.intake_state = intake_state
        if hotel_pref_state is not None:
            self.hotel_pref_state = hotel_pref_state
        if initial_plan_complete is not None:
            self.initial_plan_complete = initial_plan_complete
        if planning_new_trip is not None:
            self.planning_new_trip = planning_new_trip
        if pending_trip_edit_request is not None:
            self.pending_trip_edit_request = pending_trip_edit_request
        if pending_trip_preference_request is not None:
            self.pending_trip_preference_request = pending_trip_preference_request
        if preference_replacement_state is not None:
            self.preference_replacement_state = preference_replacement_state
        if trip_data is not None:
            self.trip_data = trip_data
        if pending_hotel_selection is not None:
            self.pending_hotel_selection = pending_hotel_selection
        if pending_place_selection is not None:
            self.pending_place_selection = pending_place_selection

    @property
    def intake_state(self) -> TripIntakeState:
        return TripIntakeState.from_dict(self.state["intake"])

    @intake_state.setter
    def intake_state(self, value: TripIntakeState) -> None:
        self.state["intake"] = value.to_dict()

    @property
    def hotel_pref_state(self) -> HotelPreferenceState:
        return HotelPreferenceState.from_dict(self.state["hotel_prefs"])

    @hotel_pref_state.setter
    def hotel_pref_state(self, value: HotelPreferenceState) -> None:
        self.state["hotel_prefs"] = value.to_dict()

    @property
    def trip_data(self) -> dict[str, Any] | None:
        return self.state["trip_data"]

    @trip_data.setter
    def trip_data(self, value: dict[str, Any] | None) -> None:
        self.state["trip_data"] = value

    @property
    def pending_hotel_selection(self) -> dict[str, Any] | None:
        return self.state["pending_hotel_selection"]

    @pending_hotel_selection.setter
    def pending_hotel_selection(self, value: dict[str, Any] | None) -> None:
        self.state["pending_hotel_selection"] = value

    @property
    def pending_place_selection(self) -> dict[str, Any] | None:
        return self.state.get("pending_place_selection")

    @pending_place_selection.setter
    def pending_place_selection(self, value: dict[str, Any] | None) -> None:
        self.state["pending_place_selection"] = value

    @property
    def language(self) -> str:
        return str(self.state.get("language") or "vi")

    @language.setter
    def language(self, value: str) -> None:
        self.state["language"] = value if value in SUPPORTED_LANGUAGES else "vi"

    @property
    def initial_plan_complete(self) -> bool:
        return self.state["initial_plan_complete"]

    @initial_plan_complete.setter
    def initial_plan_complete(self, value: bool) -> None:
        self.state["initial_plan_complete"] = value

    @property
    def planning_new_trip(self) -> bool:
        return self.state["planning_new_trip"]

    @planning_new_trip.setter
    def planning_new_trip(self, value: bool) -> None:
        self.state["planning_new_trip"] = value

    @property
    def pending_trip_edit_request(self) -> str | None:
        return self.state["pending_trip_edit_request"]

    @pending_trip_edit_request.setter
    def pending_trip_edit_request(self, value: str | None) -> None:
        self.state["pending_trip_edit_request"] = value

    @property
    def pending_trip_preference_request(self) -> str | None:
        return self.state["pending_trip_preference_request"]

    @pending_trip_preference_request.setter
    def pending_trip_preference_request(self, value: str | None) -> None:
        self.state["pending_trip_preference_request"] = value

    @property
    def preference_replacement_state(self) -> TripIntakeState | None:
        value = self.state["preference_replacement_state"]
        return TripIntakeState.from_dict(value) if value is not None else None

    @preference_replacement_state.setter
    def preference_replacement_state(self, value: TripIntakeState | None) -> None:
        self.state["preference_replacement_state"] = value.to_dict() if value is not None else None

    @property
    def pending_parameter_confirmation(self) -> bool:
        return self.state["pending_parameter_confirmation"]

    @pending_parameter_confirmation.setter
    def pending_parameter_confirmation(self, value: bool) -> None:
        self.state["pending_parameter_confirmation"] = value


def create_chat_session(
    session_id: str,
    *,
    persist_hook: Callable[[TripSession], None] | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    owner_user_id: str | None = None,
) -> TripSession:
    """Build a fresh session with its own compiled agent and tool closures, so no
    tool ever reaches for a module-level file constant shared by every
    conversation."""
    session = TripSession(
        session_id=session_id,
        config={"configurable": {"thread_id": session_id}},
        persist_hook=persist_hook,
        owner_user_id=owner_user_id,
    )
    pass
    return session


def _load_pending_hotel_selection(session: TripSession) -> dict[str, Any] | None:
    return session.pending_hotel_selection


def _clear_pending_hotel_selection(session: TripSession) -> None:
    if session.pending_hotel_selection is not None:
        session.pending_hotel_selection = None


def _load_pending_place_selection(session: TripSession) -> dict[str, Any] | None:
    return session.pending_place_selection


def _clear_pending_place_selection(session: TripSession) -> None:
    if session.pending_place_selection is not None:
        session.pending_place_selection = None
        if session.persist_hook:
            session.persist_hook(session)


def clear_session_history(session: TripSession) -> None:
    """Clear transient current trip plan, pending hotel selection, and intake/hotel
    preference state for one session — the per-session equivalent of the former
    global file cleanup."""
    session.trip_data = None
    session.pending_hotel_selection = None
    session.pending_place_selection = None
    session.intake_state = TripIntakeState()
    session.hotel_pref_state = HotelPreferenceState()
    session.initial_plan_complete = False
    session.planning_new_trip = False
    session.pending_trip_edit_request = None
    session.pending_trip_preference_request = None
    session.preference_replacement_state = None
    if session.persist_hook:
        session.persist_hook(session)


def cli_persist_hook(session: TripSession) -> None:
    """The CLI's persist_hook: keep writing both legacy JSON files under data/, so
    the terminal tool stays genuinely useful across restarts. Installed only by
    the CLI — the server leaves persist_hook unset by default."""
    session_data_dir = Path("data")
    session_data_dir.mkdir(parents=True, exist_ok=True)
    current_trip_plan_file = session_data_dir / "current_trip_plan.json"
    pending_hotel_selection_file = session_data_dir / "pending_hotel_selection.json"

    if session.trip_data is not None:
        with open(current_trip_plan_file, "w", encoding="utf-8") as file_handle:
            json.dump(session.trip_data, file_handle, ensure_ascii=False, indent=2)
    elif current_trip_plan_file.exists():
        current_trip_plan_file.unlink()

    if session.pending_hotel_selection is not None:
        with open(pending_hotel_selection_file, "w", encoding="utf-8") as file_handle:
            json.dump(session.pending_hotel_selection, file_handle, ensure_ascii=False, indent=2)
    elif pending_hotel_selection_file.exists():
        pending_hotel_selection_file.unlink()

    pending_place_selection_file = session_data_dir / "pending_place_selection.json"
    if session.pending_place_selection is not None:
        with open(pending_place_selection_file, "w", encoding="utf-8") as file_handle:
            json.dump(session.pending_place_selection, file_handle, ensure_ascii=False, indent=2)
    elif pending_place_selection_file.exists():
        pending_place_selection_file.unlink()


def debug_persist_hook(session: TripSession) -> None:
    """Opt-in (DEBUG_TRIP_PLAN_FILE=1) debug hook: writes to debug/{session_id}/,
    never to the bare global filenames — those would re-create the exact
    cross-session bug this phase removes.

    session_id is client-supplied and interpolated into a filesystem path, so it
    is validated here, at the write site, not only at Phase 3's HTTP boundary —
    the CLI itself reaches this same hook shape with the non-UUID literal
    "poc_trip_planner_1", which must still be accepted.
    """
    if not _SESSION_ID_PATTERN.fullmatch(session.session_id):
        raise ValueError(
            f"Refusing to write debug trip-plan files for an unsafe session_id: {session.session_id!r}"
        )

    debug_dir = Path("debug") / session.session_id
    debug_dir.mkdir(parents=True, exist_ok=True)

    trip_plan_file = debug_dir / "current_trip_plan.json"
    pending_file = debug_dir / "pending_hotel_selection.json"

    if session.trip_data is not None:
        with open(trip_plan_file, "w", encoding="utf-8") as file_handle:
            json.dump(session.trip_data, file_handle, ensure_ascii=False, indent=2)
    elif trip_plan_file.exists():
        trip_plan_file.unlink()

    if session.pending_hotel_selection is not None:
        with open(pending_file, "w", encoding="utf-8") as file_handle:
            json.dump(session.pending_hotel_selection, file_handle, ensure_ascii=False, indent=2)

    pending_place_file = debug_dir / "pending_place_selection.json"
    if session.pending_place_selection is not None:
        with open(pending_place_file, "w", encoding="utf-8") as file_handle:
            json.dump(session.pending_place_selection, file_handle, ensure_ascii=False, indent=2)
    elif pending_file.exists():
        pending_file.unlink()


def supabase_persist_hook(session: TripSession) -> None:
    """Best-effort persistence: database outages must not fail a chat turn."""
    for attempt in range(2):
        try:
            if not _SESSION_ID_PATTERN.fullmatch(session.session_id):
                raise ValueError("Unsafe session id for persistent storage.")
            from src.services.session_store import upsert

            upsert(session)
            return
        except Exception:
            if attempt == 0:
                logger.warning(
                    "Session persistence failed; retrying once",
                    extra={"session_id": session.session_id, "attempt": attempt + 1},
                    exc_info=True,
                )
                continue
            logger.exception(
                "Unable to persist session; continuing in memory",
                extra={"session_id": session.session_id, "attempt": attempt + 1},
            )


class SessionRegistry:
    """In-memory, TTL-evicted store of TripSessions. Process-local — run one
    uvicorn worker; multi-worker needs Supabase-backed sessions (out of scope).

    Handlers are sync `def`, so these run on real OS threads: every mutation of
    the internal dict must hold `_registry_lock`. A per-session lock cannot
    protect the lookup that produces the session — two concurrent requests
    carrying the same not-yet-registered session_id could otherwise each build a
    distinct TripSession with a distinct lock, and the loser's work is silently
    discarded.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_SESSION_TTL_SECONDS,
        cap: int = DEFAULT_SESSION_CAP,
        persist_hook: Callable[[TripSession], None] | None = None,
        load_hook: Callable[[str], dict[str, Any] | None] | None = None,
        delete_hook: Callable[[str], None] | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        self._sessions: dict[str, TripSession] = {}
        self._registry_lock = threading.Lock()
        self._ttl_seconds = ttl_seconds
        self._cap = cap
        self._persist_hook = persist_hook
        self._load_hook = load_hook
        self._delete_hook = delete_hook
        self._checkpointer = checkpointer

    def set_checkpointer(self, checkpointer: BaseCheckpointSaver) -> None:
        """Injection point for `src/main.py`'s lifespan. `registry` is a
        module-level object built at import time -- before the lifespan runs
        -- so it cannot receive the app-wide checkpointer via `__init__`;
        this sets it once, before any request creates a session."""
        self._checkpointer = checkpointer

    @property
    def checkpointer(self) -> BaseCheckpointSaver | None:
        """Read-only access to the app-lifespan checkpointer, for shared
        infra (the graph plane in `agents/graph`) that needs the same
        Postgres/MemorySaver instance sessions use -- without reaching into
        the private `_checkpointer` attribute or duplicating
        `set_checkpointer`'s injection timing."""
        return self._checkpointer

    def create(self, *, owner_user_id: str | None = None) -> TripSession:
        """The only way a session comes into being with a server-generated id."""
        import uuid

        session_id = str(uuid.uuid4())
        with self._registry_lock:
            session = create_chat_session(
                session_id,
                persist_hook=self._persist_hook,
                checkpointer=self._checkpointer,
                owner_user_id=owner_user_id,
            )
            self._sessions[session_id] = session
            return session

    def get(self, session_id: str) -> TripSession | None:
        """Look up an existing session without creating one.  Returns None when
        the session_id is unknown — callers should raise 404 in that case.

        This is the correct method for the planner_chat endpoint: the server
        must never create a session it did not issue via POST /chat/session.
        """
        with self._registry_lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_seen_at = time.time()
                return session

            if self._load_hook is not None:
                try:
                    row = self._load_hook(session_id)
                except Exception:
                    logger.exception("Unable to rehydrate session %s; treating as unavailable", session_id)
                    row = None
                if row is not None:
                    from src.services.itinerary_store import ItineraryStore
                    from src.services.session_store import _CONTEXT_SCHEMA_VERSION_V3, deserialize

                    session = create_chat_session(
                        session_id,
                        persist_hook=self._persist_hook,
                        checkpointer=self._checkpointer,
                        owner_user_id=row.get("user_id"),
                    )
                    context_data = row.get("context_data") or {}
                    session.state = deserialize(session_id, context_data, row.get("messages"))
                    # v3 rows come from the graph plane, which reads `trip_data`
                    # from its own checkpointer — rebuilding it into
                    # `TripSession.state` here would create a second copy that
                    # nothing on the HTTP path reads and nothing keeps current.
                    # Older rows still get the legacy rehydration they need.
                    if context_data.get("schema_version") != _CONTEXT_SCHEMA_VERSION_V3:
                        current_trip = context_data.get("current_trip") or {}
                        itinerary_id = current_trip.get("itinerary_id")
                        if itinerary_id:
                            session.state["trip_data"] = ItineraryStore.from_default().load_session_trip_data(
                                str(itinerary_id)
                            )
                    created_at = row.get("created_at")
                    if isinstance(created_at, str):
                        try:
                            session.created_at = datetime.fromisoformat(
                                created_at.replace("Z", "+00:00")
                            ).timestamp()
                        except ValueError:
                            logger.warning("Ignoring invalid created_at for session %s", session_id)
                    session.last_seen_at = time.time()
                    self._sessions[session_id] = session
                    return session

            # Last resort: the graph_v2 checkpointer itself. `_run_turn_via_graph`
            # never touches TripSession.state, so a thread the checkpointer already
            # knows about is a live session even when its `sessions` row is missing
            # (e.g. create_session()'s persist upsert failed silently -- see
            # supabase_persist_hook's best-effort retry) or persistence is
            # disabled. Without this, a process restart wipes the in-memory dict
            # and every such session 404s here while GET /chat/{id}/plan -- which
            # reads the same checkpointer directly -- still reports it as alive.
            if self._checkpointer is not None:
                try:
                    exists = self._checkpointer.get_tuple({"configurable": {"thread_id": session_id}}) is not None
                except Exception:
                    logger.exception("Unable to check checkpointer state for session %s", session_id)
                    exists = False
                if exists:
                    session = create_chat_session(
                        session_id, persist_hook=self._persist_hook, checkpointer=self._checkpointer
                    )
                    session.last_seen_at = time.time()
                    self._sessions[session_id] = session
                    return session

            return None

    def resolve(self, session_id: str, *, owner_user_id: str | None = None) -> TripSession:
        """Atomically look up or create a session for a caller-supplied id.

        Holding _registry_lock for the whole check-then-create closes the race
        where two concurrent requests for the same not-yet-registered id would
        otherwise each build a distinct TripSession with a distinct lock.

        Used internally by POST /chat/session only — it is the one endpoint
        allowed to auto-create sessions.  All other endpoints call get().
        """
        with self._registry_lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = create_chat_session(
                    session_id,
                    persist_hook=self._persist_hook,
                    checkpointer=self._checkpointer,
                    owner_user_id=owner_user_id,
                )
                self._sessions[session_id] = session
            session.last_seen_at = time.time()
            return session

    def drop(self, session_id: str) -> None:
        with self._registry_lock:
            self._sessions.pop(session_id, None)
            if self._delete_hook is not None:
                try:
                    self._delete_hook(session_id)
                except Exception:
                    logger.exception("Unable to delete persisted session %s", session_id)
        self._prune_checkpoints([session_id])

    def __len__(self) -> int:
        with self._registry_lock:
            return len(self._sessions)

    def _prune_checkpoints(self, session_ids: list[str]) -> None:
        """Deletes each session's LangGraph checkpoints -- the pruning policy
        for `checkpointer_backend='postgres'`. Piggybacks on the same
        opportunistic, request-triggered pattern `evict_expired` already uses
        instead of a separate scheduler dependency. No-op for 'memory' and
        for CLI/script sessions, both of which run with no checkpointer
        injected (`self._checkpointer is None`).

        Runs after the caller has released `_registry_lock` (deleting is a
        potentially slow DB call). A concurrent `get()`/`resolve()` could have
        recreated one of these ids in that window, so each id is re-checked
        under the lock immediately before its delete -- skipping ids that came
        back keeps a live session's checkpoints from being wiped out from
        under it."""
        if self._checkpointer is None:
            return
        for session_id in session_ids:
            with self._registry_lock:
                if session_id in self._sessions:
                    continue
            try:
                self._checkpointer.delete_thread(session_id)
            except Exception:
                logger.exception("Unable to prune checkpoints for session %s", session_id)

    def evict_expired(self) -> int:
        """Evict sessions past the TTL, then trim to the size cap by oldest
        last_seen_at (LRU). MUST skip any session whose lock is currently held
        (non-blocking lock.locked() check) — otherwise a session inside a 60s
        tool call could be evicted mid-request, and the next request for the same
        id builds a fresh session that runs concurrently with the in-flight one.
        """
        now = time.time()
        evicted = 0
        pruned_ids: list[str] = []
        with self._registry_lock:
            expired_ids = [
                session_id
                for session_id, session in self._sessions.items()
                if now - session.last_seen_at > self._ttl_seconds and not session.lock.locked()
            ]
            for session_id in expired_ids:
                del self._sessions[session_id]
                evicted += 1
            pruned_ids.extend(expired_ids)

            if len(self._sessions) > self._cap:
                evictable = sorted(
                    (session for session in self._sessions.values() if not session.lock.locked()),
                    key=lambda session: session.last_seen_at,
                )
                overflow = len(self._sessions) - self._cap
                for session in evictable[:overflow]:
                    del self._sessions[session.session_id]
                    evicted += 1
                    pruned_ids.append(session.session_id)

        self._prune_checkpoints(pruned_ids)

        return evicted

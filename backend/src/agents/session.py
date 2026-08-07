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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.graph import build_trip_agent
from src.agents.routing_decision import (
    Route,
    RouteContext,
    _is_hotel_choice_attempt,
    _new_trip_signal,
    _normalize_intent_text,
    _VALID_ROUTES,
    decide_route_by_rules,
    route_context_from_state,
    validate_route,
)
from src.agents.state import TripState, initial_state
from src.agents.supervisor import decide_route_by_llm
from src.config import get_settings
from src.i18n import SUPPORTED_LANGUAGES, t
from src.services.hotel_selection import HotelPreferenceState, _has_budget_signal
from src.services.trip_edit_planner import TripEditPlan, TripEditPlanError, plan_trip_edit
from src.services.trip_intake import (
    TripIntakeState,
    TripPreferenceUpdate,
    TripPreferenceUpdateError,
    _llm_extract_intake_facts,
    _match_known_destination,
)
from src.services.trip_planner import (
    _get_destination_names,
    resolve_trip_edit_request,
)

logger = logging.getLogger(__name__)

_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

DEFAULT_SESSION_TTL_SECONDS = 2 * 60 * 60
DEFAULT_SESSION_CAP = 200


@dataclass
class TurnResult:
    """Thin carrier returned by process_chat_turn so the HTTP layer can derive
    `stage` without re-implementing routing logic.

    text  — the user-facing reply string (may start with "SYSTEM ERROR:").
    tool  — the name of the tool that actually ran, or None when the turn only
            asked a question (intake / hotel-preference gate / edit clarify).
            Values: 'select_hotel' | 'finalize_trip_plan' |
                    'execute_trip_edit_request' | 'recommend_hotels' |
                    'agent_stream' | None.
    """

    text: str
    tool: str | None = None


_STAGE_MAP: dict[str | None, str] = {
    "select_hotel": "planned",
    "finalize_trip_plan": "finalized",
    "execute_trip_edit_request": "modified",
    "recommend_hotels": "hotel_options",
}


def derive_stage(result: TurnResult, session: TripSession | None = None) -> str:
    """Derive the `stage` value from a TurnResult.

    Keeps stage derivation in one place — do NOT re-derive it in the endpoint
    handler or per branch of process_chat_turn.
    """
    if result.text.startswith("SYSTEM ERROR:"):
        return "error"
    if session and (result.tool == "agent_stream" or result.tool is None or result.tool == "chat"):
        if getattr(session, "initial_plan_complete", False):
            return "modified" if getattr(session, "pending_trip_edit_request", None) else "planned"
        if getattr(session, "pending_hotel_selection", None):
            return "hotel_options"
    return _STAGE_MAP.get(result.tool, "intake")


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
        agent: Any,
        config: dict,
        *,
        tools: Any = None,  # SessionTools — set by create_chat_session via build_trip_agent
        persist_hook: Callable[[TripSession], None] | None = None,
        created_at: float | None = None,
        last_seen_at: float | None = None,
        lock: threading.Lock | None = None,
        state: TripState | None = None,
        intake_state: TripIntakeState | None = None,
        hotel_pref_state: HotelPreferenceState | None = None,
        initial_plan_complete: bool | None = None,
        planning_new_trip: bool | None = None,
        pending_trip_edit_request: str | None = None,
        pending_trip_preference_request: str | None = None,
        preference_replacement_state: TripIntakeState | None = None,
        trip_data: dict[str, Any] | None = None,
        pending_hotel_selection: dict[str, Any] | None = None,
    ) -> None:
        self.session_id = session_id
        self.agent = agent
        self.config = config
        self.tools = tools
        self.persist_hook = persist_hook
        self.created_at = created_at if created_at is not None else time.time()
        self.last_seen_at = last_seen_at if last_seen_at is not None else time.time()
        self.lock = lock if lock is not None else threading.Lock()
        self.state: TripState = state if state is not None else initial_state(session_id)

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


def create_chat_session(session_id: str, *, persist_hook: Callable[[TripSession], None] | None = None) -> TripSession:
    """Build a fresh session with its own compiled agent and tool closures, so no
    tool ever reaches for a module-level file constant shared by every
    conversation."""
    session = TripSession(
        session_id=session_id,
        agent=None,
        config={"configurable": {"thread_id": session_id}},
        persist_hook=persist_hook,
    )
    session.agent, session.tools = build_trip_agent(session)
    return session


def _load_pending_hotel_selection(session: TripSession) -> dict[str, Any] | None:
    return session.pending_hotel_selection


def _clear_pending_hotel_selection(session: TripSession) -> None:
    if session.pending_hotel_selection is not None:
        session.pending_hotel_selection = None
        if session.persist_hook:
            session.persist_hook(session)


def clear_session_history(session: TripSession) -> None:
    """Clear transient current trip plan, pending hotel selection, and intake/hotel
    preference state for one session — the per-session equivalent of the former
    global file cleanup."""
    session.trip_data = None
    session.pending_hotel_selection = None
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
    elif pending_file.exists():
        pending_file.unlink()


def supabase_persist_hook(session: TripSession) -> None:
    """Best-effort persistence: database outages must not fail a chat turn."""
    try:
        if not _SESSION_ID_PATTERN.fullmatch(session.session_id):
            raise ValueError("Unsafe session id for persistent storage.")
        from src.services.session_store import upsert

        upsert(session)
    except Exception:
        logger.exception("Unable to persist session %s; continuing in memory", session.session_id)


def suggestions_for(session: TripSession) -> list[dict[str, str]]:
    """Tappable quick-reply chips for the state the conversation is now in, as
    [{"label", "value"}] — `value` is what to send when tapped.

    Declared here rather than inferred by the UI. A UI that scans the reply for
    lines like "1. ..." cannot tell a real menu from the model's own prose, and
    the model writes numbered lists constantly ("1. **Điểm đến** ... 2. **Thời
    gian** ..."). Those became chips that sent a bare "1" into a turn expecting
    free text — the answer then had nothing to do with what was asked.

    Empty means the turn wants free text, which is the common case.
    """
    if session.pending_hotel_selection is not None:
        return []


    if session.initial_plan_complete or not session.intake_state.is_complete:
        return []

    return [
        {"label": f"{index}. {label}", "value": str(index)}
        for index, label in enumerate(session.hotel_pref_state.suggestion_options(), start=1)
    ]


def _looks_like_textual_tool_call(content: object) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text.startswith("{") and '"name"' in text and (
            '"parameters"' in text or '"arguments"' in text
        )
    return isinstance(payload, dict) and bool(payload.get("name")) and any(
        key in payload for key in ("parameters", "arguments")
    )


def _unsupported_destination_reply(user_input: str) -> str | None:
    """Reply to use when a message clearly asks for a new trip but names a place we
    have no data for. Without this the message falls through to the saved-plan edit
    planner, which answers "không thể hiểu yêu cầu chỉnh sửa" — the user asked to go
    to Hội An and is told their edit was unclear, with no hint of the real reason.

    Keys off the place the user actually NAMED, not merely off a failure to ground
    one. An edit like "sau 20h tôi không muốn đi đâu nữa" names no place at all and
    must stay on the edit path; only a named-but-unknown city belongs here.
    """
    if _new_trip_signal(user_input) is None:
        return None
    destination_names = _get_destination_names()
    named = str(
        (_llm_extract_intake_facts(user_input, {}, destination_names) or {}).get("destination") or ""
    ).strip()
    if not named or named.casefold() == "null":
        return None
    if _match_known_destination(named, destination_names):
        return None
    return TripIntakeState().next_question(destination_names)


def _begin_new_trip_if_requested(session: TripSession, user_input: str) -> bool:
    signal = _new_trip_signal(user_input)
    if signal is None:
        return False
    fresh_intake = TripIntakeState().with_message(user_input, _get_destination_names())
    if signal != "strong" and not fresh_intake.destination:
        return False
    session.intake_state = fresh_intake
    session.hotel_pref_state = HotelPreferenceState()
    session.pending_trip_edit_request = None
    session.initial_plan_complete = False
    session.planning_new_trip = True
    return True


_TRIP_PREFERENCE_CHANGE_WORDS = re.compile(
    r"\b(?:doi|sua|thay|cap nhat|chuyen|change|update|prefer)\b"
)
_TRIP_PREFERENCE_FIELD_WORDS = re.compile(
    r"\b(?:ngay|so ngay|thoi gian|nguoi|so nguoi|bat dau|khoi hanh|diem den|"
    r"destination|days?|people|travelers?|start date|vibe|phong cach|so thich|uu tien)\b"
)
_SUPPORTED_VIBE_WORDS = re.compile(
    r"\b(?:bien|van hoa|am thuc|thien nhien|lich su|mua sam|cuoc song ve dem|tre em)\b"
)


def _looks_like_trip_preference_change(user_input: str) -> bool:
    if "?" in user_input:
        return False
    normalized = _normalize_intent_text(user_input)
    if _TRIP_PREFERENCE_CHANGE_WORDS.search(normalized) and _TRIP_PREFERENCE_FIELD_WORDS.search(normalized):
        return True
    return bool(
        re.search(r"\b(?:muon|thich|uu tien|prefer)\b", normalized)
        and (_TRIP_PREFERENCE_FIELD_WORDS.search(normalized) or _SUPPORTED_VIBE_WORDS.search(normalized))
    )


def _preference_state_from_session(session: TripSession) -> TripIntakeState:
    if session.trip_data is None:
        return session.intake_state
    itinerary_rows = session.trip_data.get("itineraries") or [{}]
    itinerary = itinerary_rows[0] if isinstance(itinerary_rows, list) else itinerary_rows
    if not isinstance(itinerary, dict):
        return session.intake_state
    preferences = [str(value) for value in itinerary.get("preferences") or [] if str(value).strip()]
    return TripIntakeState(
        destination=preferences[0] if preferences else session.intake_state.destination,
        duration=f"{int(itinerary.get('duration_days') or 1)} ngày",
        start_date=str(itinerary.get("start_date") or "").strip() or session.intake_state.start_date,
        people=f"{int(itinerary.get('number_of_adults') or 1)} người",
        preferences=tuple(preferences[1:]),
    )


def _recommend_preference_replacement(session: TripSession) -> str:
    state = session.preference_replacement_state
    if state is None or not state.is_complete:
        return t("SYSTEM ERROR: Thông tin thay đổi chuyến đi chưa đầy đủ.", session.language)
    if not session.hotel_pref_state.is_complete:
        return session.hotel_pref_state.next_question(session.language) or t(
            "Bạn muốn ngân sách khách sạn khoảng bao nhiêu?", session.language
        )

    arguments = {**state.tool_arguments(), **session.hotel_pref_state.tool_arguments()}
    response = str(session.tools.recommend_hotels.invoke(arguments))
    if response.startswith("SYSTEM ERROR:"):
        return response
    if session.pending_hotel_selection is None:
        return t("SYSTEM ERROR: Không thể lưu danh sách khách sạn mới.", session.language)

    if session.trip_data is not None:
        replacement = dict(session.pending_hotel_selection)
        replacement["mode"] = "replace_trip_preferences"
        session.pending_hotel_selection = replacement
        if session.persist_hook:
            session.persist_hook(session)
    session.intake_state = state
    session.preference_replacement_state = None
    return response


def _start_trip_preference_update(session: TripSession, update: TripPreferenceUpdate) -> str:
    updated = update.apply_to(_preference_state_from_session(session), _get_destination_names())
    session.intake_state = updated
    session.preference_replacement_state = updated
    session.pending_trip_preference_request = None
    _clear_pending_hotel_selection(session)
    if not updated.is_complete:
        return updated.next_question(_get_destination_names(), session.language) or t(
            "Vui lòng bổ sung thông tin chuyến đi.", session.language
        )
    if not session.hotel_pref_state.is_complete:
        return session.hotel_pref_state.next_question(session.language) or t(
            "Bạn muốn ngân sách khách sạn khoảng bao nhiêu?", session.language
        )
    return _recommend_preference_replacement(session)


def execute_trip_edit_request(session: TripSession, modification_request: str, plan: TripEditPlan) -> str | None:
    """Thin session-bound wrapper around trip_planner.resolve_trip_edit_request
    (Phase 4, 260802-1437-langgraph-full-orchestration-and-durable-state).

    Called directly from process_chat_turn's _run_edit_draft, not by the LLM
    — that is why it lives here rather than as an agent-visible @tool. Kept
    at this exact name and signature because the modify_trip_plan tool now
    calls resolve_trip_edit_request directly (it has no TripSession to pass
    here — that dependency would recreate the circular import this phase
    removes from the other three tools), and because many existing tests
    monkeypatch `session_module.execute_trip_edit_request` directly.

    A `update_trip_preferences` operation is intercepted here, before
    delegating to the pure `resolve_trip_edit_request`: applying it needs
    session-bound tool invocation (recommend_hotels) the same way the direct
    preference-update path in `process_chat_turn` does, so it reuses
    `_start_trip_preference_update` rather than being pure.
    """
    preference_update = next(
        (operation for operation in plan.operations if operation.operation == "update_trip_preferences"),
        None,
    )
    if preference_update:
        saved_itinerary = ((session.trip_data or {}).get("itineraries") or [{}])[0]
        if isinstance(saved_itinerary, dict) and str(saved_itinerary.get("status") or "").casefold() == "finalized":
            return t(
                "Kế hoạch đã xác nhận không thể chỉnh sửa. Hãy tạo một kế hoạch mới nếu cần thay đổi.",
                session.language,
            )
        if preference_update.trip_preferences is None:
            return t("SYSTEM ERROR: Yêu cầu thay đổi thông tin chuyến đi không hợp lệ.", session.language)
        try:
            return _start_trip_preference_update(session, preference_update.trip_preferences)
        except TripPreferenceUpdateError as exc:
            return t(
                "Mình chưa thể xác nhận thay đổi {exc} Bạn vui lòng nói rõ lại nhé.",
                session.language,
                exc=exc,
            )

    reply, updates = resolve_trip_edit_request(
        session.trip_data, modification_request, plan, language=session.language
    )
    session.state.update(updates)
    return reply


def _decide_route(session: TripSession, context: RouteContext, user_input: str) -> Route:
    """Supervisor proposes, `validate_route` checks, `decide_route_by_rules` is
    the deterministic fallback (D3). Logs the final route and, when the
    supervisor's proposal was not used, why — llm_failed | invalid_label |
    impossible_route | flag_off — so Phase 4's measurements can tell wiring
    bugs apart from model-quality issues."""
    if not get_settings().trip_supervisor_router:
        route = decide_route_by_rules(context, user_input)
        logger.info("Route decided: %s (reason=flag_off)", route)
        return route

    proposed = decide_route_by_llm(session, user_input)
    if proposed is None:
        route = decide_route_by_rules(context, user_input)
        logger.info("Route decided: %s (reason=llm_failed)", route)
        return route

    if proposed not in _VALID_ROUTES:
        route = decide_route_by_rules(context, user_input)
        logger.info("Route decided: %s (reason=invalid_label, proposed=%s)", route, proposed)
        return route

    validated = validate_route(proposed, context)
    if validated is None:
        route = decide_route_by_rules(context, user_input)
        logger.info("Route decided: %s (reason=impossible_route, proposed=%s)", route, proposed)
        return route

    logger.info("Route decided: %s (reason=supervisor)", validated)
    return validated


def _process_chat_turn(
    session: TripSession,
    user_input: str,
    stay_dates: tuple[str, str] | None = None,
    language: str = "vi",
) -> TurnResult:
    """Handle exactly one chat turn and return a TurnResult. Mutates `session`
    in place. Callers own their own input loop / HTTP request cycle — this
    function never blocks on input() and never prints.

    The returned TurnResult.tool records which tool actually ran so that the
    HTTP layer can derive `stage` without re-implementing routing logic. The
    CLI caller uses .text directly.

    `language` ("vi" | "en") is stored on `session.state["language"]` and
    drives every deterministic (non-LLM) reply via `t(..., language)`. An
    unrecognized value falls back to "vi" through the setter.
    """
    logger.info("User Input: %s", user_input)
    session.last_seen_at = time.time()
    session.language = language

    if stay_dates:
        try:
            session.intake_state = session.intake_state.with_stay_dates(*stay_dates)
            logger.info("Explicit stay dates applied via UI: %s", stay_dates)
            user_input = ""
        except ValueError as exc:
            return TurnResult(text=str(exc), tool=None)
    # A trip-preference change is handled before routing, regardless of what
    # the supervisor/rules would otherwise pick — it can arrive mid-hotel-list
    # or once intake+budget are both already resolved (but before a trip is
    # built), and always takes priority. Also requires the deterministic
    # pipeline to have ALREADY finished once — plain "no trip_data yet" is
    # true for the entire intake window including its very first turn, and
    # the intake form's composed message always opens with "Tôi muốn đi ...
    # trong N ngày ... cho N người", which itself satisfies
    # `_looks_like_trip_preference_change` (muốn + ngày/người). Without the
    # extra check, that hijacked every fresh-session first turn into this
    # "change an already-confirmed fact" flow instead of the deterministic
    # one, silently dropping anything TripPreferenceUpdate doesn't know about
    # (budget, companions, pace, day_rhythm, notes). `trip_data is None` is
    # kept as the outer bound so this never fires once a trip is built —
    # `_run_edit_draft` owns edits to an already-built itinerary.
    intake_pipeline_already_resolved = (
        session.trip_data is None
        and session.intake_state.is_complete
        and session.hotel_pref_state.is_complete
    )
    direct_preference_update = bool(
        session.pending_trip_preference_request
        or (
            (session.pending_hotel_selection is not None or intake_pipeline_already_resolved)
            and _looks_like_trip_preference_change(user_input)
        )
    )

    if session.pending_parameter_confirmation and not direct_preference_update:
        session.pending_parameter_confirmation = False
        user_input = "Hãy tìm thêm khách sạn theo yêu cầu mới nhất của tôi."
        # Fall through to let the LLM supervisor run recommend_hotels based on this input.

    if direct_preference_update:
        request = user_input
        if session.pending_trip_preference_request:
            request = f"{session.pending_trip_preference_request}\nLàm rõ của người dùng: {user_input}"
        try:
            update = TripPreferenceUpdate.from_message(
                request,
                _preference_state_from_session(session),
                _get_destination_names(),
            )
            response = _start_trip_preference_update(session, update)
            session.pending_parameter_confirmation = True
            response += "\nBạn đã chỉnh sửa xong chưa? (Báo lại để mình tìm khách sạn mới nhé)."
        except TripPreferenceUpdateError as exc:
            session.pending_trip_preference_request = request
            return TurnResult(
                text=t(
                    "Mình chưa thể xác nhận {exc} Hãy chọn một sở thích được hỗ trợ hoặc nói rõ thông tin muốn đổi.",
                    session.language,
                    exc=exc,
                ),
                tool=None,
            )
        tool = "recommend_hotels" if session.pending_hotel_selection is not None else None
        return TurnResult(text=response, tool=tool)

    if session.preference_replacement_state is not None:
        if not session.hotel_pref_state.is_complete:
            session.hotel_pref_state = session.hotel_pref_state.with_message(user_input)
            question = session.hotel_pref_state.next_question(session.language)
            if question:
                return TurnResult(text=question, tool=None)
        response = _recommend_preference_replacement(session)
        tool = "recommend_hotels" if session.pending_hotel_selection is not None else None
        return TurnResult(text=response, tool=tool)

    context = route_context_from_state(session.state)
    route = _decide_route(session, context, user_input)

    if route == "finalize":
        return _run_finalize(session)

    is_saved_plan_edit = False
    if route in ("new_trip", "edit_draft"):
        has_saved_plan = session.trip_data is not None
        if has_saved_plan and not session.planning_new_trip:
            if not _begin_new_trip_if_requested(session, user_input):
                unsupported_reply = _unsupported_destination_reply(user_input)
                if unsupported_reply:
                    logger.info("New-trip request names an unsupported destination")
                    return TurnResult(text=unsupported_reply, tool=None)

        is_saved_plan_edit = has_saved_plan and not session.planning_new_trip
        if is_saved_plan_edit:
            result = _run_edit_draft(session, user_input)
            if result is not None:
                return result
            # edit_plan.decision == "not_edit": the saved-plan edit path is done
            # with this turn — go straight to the general agent, same as today.
            return _run_chat_agent(session, user_input)

    if not session.initial_plan_complete and not is_saved_plan_edit:
        return _run_intake(session, user_input)

    logger.warning("BEFORE STREAM, state keys: %s", session.state.keys())
    logger.warning("BEFORE STREAM, pending_hotel_selection is None: %s", session.state.get("pending_hotel_selection") is None)
    return _run_chat_agent(session, user_input)



def _handle_frontend_hotel_selection(session: TripSession, hotel_id: str) -> TurnResult:
    """Handles direct hotel selection from the frontend API."""
    pending = session.pending_hotel_selection
    if not pending:
        return TurnResult(
            text="SYSTEM ERROR: Chưa có danh sách khách sạn nào để chọn. Hãy tạo gợi ý khách sạn trước.",
            tool="select_hotel"
        )

    from src.services.trip_scheduler import PlaceCandidate
    from src.services.hotel_selection import resolve_hotel_selection
    from src.services.trip_planner import _build_trip_data, _generate_and_save_itinerary, _reapply_planning_constraints
    from src.services.trip_formatter import format_trip_response_from_json

    raw_options = pending.get("options") or []
    options = [
        (data, PlaceCandidate.from_mapping({**data, "category": "Hotel"}))
        for data in raw_options
        if isinstance(data, dict)
    ]
    resolved = resolve_hotel_selection(hotel_id, options)
    if not resolved:
        ids = [str(data.get("id")) for data, _ in options]
        return TurnResult(
            text=f"SYSTEM ERROR: Không tìm thấy khách sạn đã chọn. Looking for {hotel_id}, available: {ids}",
            tool="select_hotel"
        )

    hotel_data, _candidate = resolved
    mode = pending.get("mode", "new_trip")
    destination = pending.get("destination", "")
    duration = pending.get("duration", "")
    start_date = pending.get("start_date")
    end_date = pending.get("end_date")
    people = pending.get("people", "")
    preferences = pending.get("preferences_text", "")
    stay_kwargs = {}
    if start_date is not None or end_date is not None:
        stay_kwargs = {"start_date": start_date, "end_date": end_date}

    if mode in {"change_hotel", "replace_trip_preferences"}:
        trip_data = session.trip_data
        if trip_data is None:
            _clear_pending_hotel_selection(session)
            return TurnResult(
                text="SYSTEM ERROR: Không còn kế hoạch chuyến đi để đổi khách sạn.",
                tool="select_hotel"
            )

        saved_itinerary = (trip_data.get("itineraries") or [{}])[0]
        if isinstance(saved_itinerary, dict) and str(saved_itinerary.get("status") or "").casefold() == "finalized":
            _clear_pending_hotel_selection(session)
            return TurnResult(
                text="Kế hoạch đã xác nhận không thể chỉnh sửa. Hãy tạo một kế hoạch mới nếu cần thay đổi.",
                tool="select_hotel"
            )

        planning_constraints = pending.get("planning_constraints") or {} if mode == "change_hotel" else {}
        try:
            updated_data = _build_trip_data(
                destination,
                duration,
                people,
                preferences,
                preselected_hotel=hotel_data,
                planning_constraints=planning_constraints,
                session_id=session.session_id,
                **stay_kwargs,
            )
        except Exception as exc:
            logger.exception("Hotel change failed")
            return TurnResult(text=f"SYSTEM ERROR: {exc}", tool="select_hotel")

        adjustment = (
            "Đã đổi khách sạn và lập lại toàn bộ các cụm địa điểm theo vị trí mới."
            if mode == "change_hotel"
            else "Đã cập nhật thông tin chuyến đi, chọn lại khách sạn và lập một lịch trình mới."
        )
        updated_data.setdefault("adjustments", []).append(adjustment)
        updated_itinerary = (updated_data.get("itineraries") or [{}])[0]
        if isinstance(updated_itinerary, dict):
            updated_itinerary["status"] = "Draft"
            updated_itinerary.pop("summary", None)
            if mode == "change_hotel" and planning_constraints:
                updated_itinerary["planning_constraints"] = planning_constraints
                updated_data.setdefault("adjustments", []).extend(_reapply_planning_constraints(updated_data))
        
        session.trip_data = updated_data
        _clear_pending_hotel_selection(session)
        session.initial_plan_complete = True
        session.planning_new_trip = False
        return TurnResult(
            text=format_trip_response_from_json(updated_data),
            tool="select_hotel"
        )

    # New trip mode
    captured = {}
    def _capture_save(t_data: dict) -> None:
        captured["trip_data"] = t_data

    reply = _generate_and_save_itinerary(
        destination,
        duration,
        people,
        preferences,
        preselected_hotel=hotel_data,
        session_id=session.session_id,
        save=_capture_save,
        **stay_kwargs,
    )
    if str(reply).startswith("SYSTEM ERROR:"):
        return TurnResult(text=str(reply), tool="select_hotel")
    
    session.trip_data = captured.get("trip_data")
    _clear_pending_hotel_selection(session)
    session.initial_plan_complete = True
    session.planning_new_trip = False
    return TurnResult(
        text=str(reply),
        tool="select_hotel"
    )


def _persist_turn(session: TripSession, result: TurnResult, user_input: str | None = None) -> TurnResult:
    """Persist after a completed turn without changing the turn's outcome."""
    session.state["reply"] = result.text
    session.state["tool_ran"] = result.tool
    if user_input:
        now = datetime.now(UTC).isoformat()
        stage = derive_stage(result, session)
        session.state["messages"].extend(
            [
                HumanMessage(content=user_input, additional_kwargs={"stage": stage, "at": now}),
                AIMessage(content=result.text, additional_kwargs={"stage": stage, "at": now}),
            ]
        )
    if session.persist_hook:
        session.persist_hook(session)
    return result


def process_chat_turn(
    session: TripSession,
    user_input: str,
    stay_dates: tuple[str, str] | None = None,
    language: str = "vi",
) -> TurnResult:
    """Run one turn, then persist its business state and visible message pair."""
    result = _process_chat_turn(session, user_input, stay_dates=stay_dates, language=language)
    return _persist_turn(session, result, user_input)


def handle_frontend_hotel_selection(session: TripSession, hotel_id: str) -> TurnResult:
    """Run a direct hotel-selection action and persist its changed state."""
    return _persist_turn(session, _handle_frontend_hotel_selection(session, hotel_id))

def _run_finalize(session: TripSession) -> TurnResult:
    tool_response = session.tools.finalize_trip_plan.invoke({})
    logger.info("Finalization response: %s", tool_response)
    session.initial_plan_complete = not str(tool_response).startswith("SYSTEM ERROR:")
    return TurnResult(text=str(tool_response), tool="finalize_trip_plan")


_BUDGET_KEYWORDS = re.compile(
    r"ng[aâ]n s[aá]ch|budget|gi[aá] ph[oò]ng|ti[eề]n ph[oò]ng|gi[aá] ti[eề]n"
    r"|chi ph[ií]|ph[ií] l[uư]u tr[uú]|ph[ií] ph[oò]ng|t[oố]i [dđ]a|ph[ií] [dđ][eê]m"
    r"|300k|300\.000|500k|500\.000|1 tri[eệ]u|2 tri[eệ]u|\d+[kK] ?vnd|\d+ ?tri[eệ]u",
    re.IGNORECASE,
)
_BUDGET_CHANGE_VERBS = re.compile(
    r"\b(?:[dđ][oổ]i|thay|gi[aả]m|h[aạ]|c[aâ]p nh[aậ]t|change|lower|reduce|update)\b",
    re.IGNORECASE,
)


def _looks_like_budget_change(text: str) -> bool:
    """Heuristic: True when the user is clearly asking to change the hotel
    budget / price ceiling on an existing trip — used as the deterministic
    fallback when the LLM edit planner fails to classify the request."""
    return bool(_BUDGET_KEYWORDS.search(text) and _BUDGET_CHANGE_VERBS.search(text))


def _run_edit_draft(session: TripSession, user_input: str) -> TurnResult | None:
    """Returns None when `plan_trip_edit` decides `not_edit` — the caller falls
    through to the general chat agent, same as today."""
    try:
        current_data = session.trip_data
        planner_request = user_input
        if session.pending_trip_edit_request:
            planner_request = f"{session.pending_trip_edit_request}\nLàm rõ của người dùng: {user_input}"
        edit_plan = plan_trip_edit(planner_request, current_data)
    except TripEditPlanError as exc:
        logger.warning("Saved-trip edit planner failed safely: %s", exc)
        # Deterministic fallback: when the LLM fails but the message is clearly
        # a budget change, directly invoke change_hotel without relying on the
        # local model reliably mapping the request to an operation name.
        if _looks_like_budget_change(user_input):
            logger.info("Budget-change detected deterministically; falling back to change_hotel path")
            from src.services.trip_edit_planner import EditOperation, TripEditPlan
            synthetic_plan = TripEditPlan(
                decision="apply",
                summary="Thay đổi ngân sách khách sạn",
                operations=(EditOperation(operation="change_hotel", hotel_query=user_input),),
                raw_request=user_input,
            )
            tool_response = execute_trip_edit_request(session, user_input, synthetic_plan)
            tool_name = "execute_trip_edit_request"
            if session.pending_hotel_selection:
                tool_name = "recommend_hotels"
            return TurnResult(text=str(tool_response or t("SYSTEM ERROR: Không thể tìm khách sạn phù hợp với ngân sách mới.", session.language)), tool=tool_name)
        return TurnResult(
            text=t(
                "SYSTEM ERROR: Không thể hiểu an toàn yêu cầu chỉnh sửa này. Vui lòng diễn đạt cụ thể hơn.",
                session.language,
            ),
            tool=None,
        )

    if edit_plan.decision == "clarify":
        session.pending_trip_edit_request = planner_request
        return TurnResult(
            text=edit_plan.clarification_question or t("Bạn muốn chỉnh sửa phần nào của lịch trình?", session.language),
            tool=None,
        )
    session.pending_trip_edit_request = None
    if edit_plan.decision == "apply":
        tool_response = execute_trip_edit_request(session, user_input, edit_plan)
        logger.info("LLM planned modification response: %s", tool_response)
        reply_text = tool_response or t("SYSTEM ERROR: Không thể áp dụng yêu cầu chỉnh sửa này.", session.language)
        tool_name = (
            "recommend_hotels"
            if session.pending_hotel_selection
            and session.pending_hotel_selection.get("mode") == "replace_trip_preferences"
            else "execute_trip_edit_request"
        )
        return TurnResult(text=str(reply_text), tool=tool_name)
    return None


def _build_hotel_preferences(intake_state: TripIntakeState) -> str:
    """Compose the `hotel_preferences` free-text for the recommend_hotels call
    from the taxonomy fields that map to accommodation wants. companions passes
    verbatim — the labels already contain the phrase the amenity tagger matches
    (e.g. "đi cùng gia đình" contains "gia đình"). notes append verbatim (they
    were sanitized/capped in trip_intake grounding)."""
    parts: list[str] = []
    if intake_state.companions:
        parts.append(intake_state.companions)
    if intake_state.notes:
        parts.append(intake_state.notes)
    return ", ".join(parts).strip()


def _build_intake_context(intake_state: TripIntakeState) -> str:
    """Compose the travel-style context threaded into itinerary day-theme
    generation. Pace/day rhythm/notes only — companions and preferences already
    flow through their own existing params and must not be duplicated."""
    parts: list[str] = []
    if intake_state.pace:
        parts.append(f"nhịp độ: {intake_state.pace}")
    if intake_state.day_rhythm:
        parts.append("nhịp sinh hoạt: " + ", ".join(intake_state.day_rhythm))
    if intake_state.notes:
        parts.append(intake_state.notes)
    return "; ".join(parts).strip()


def _run_recommend_hotels(session: TripSession) -> TurnResult:
    verified_arguments = {
        **session.intake_state.tool_arguments(),
        **session.hotel_pref_state.tool_arguments(),
    }
    # Merge, don't overwrite: if anything ever populates these keys first, keep
    # the existing value (same shape as the dict-merge philosophy above).
    hotel_preferences = _build_hotel_preferences(session.intake_state)
    if hotel_preferences:
        verified_arguments.setdefault("hotel_preferences", hotel_preferences)
    intake_context = _build_intake_context(session.intake_state)
    if intake_context:
        verified_arguments.setdefault("intake_context", intake_context)
    logger.info("Deterministic intake complete: %s", verified_arguments)
    tool_response = session.tools.recommend_hotels.invoke(verified_arguments)
    logger.info("Final Tool Response Output:\n%s", tool_response)
    return TurnResult(text=str(tool_response), tool="recommend_hotels")


def _run_intake(session: TripSession, user_input: str) -> TurnResult:
    destination_names = _get_destination_names()
    session.intake_state = session.intake_state.with_message(user_input, destination_names)

    # 1. Ask for destination and people first
    if not session.intake_state.destination or not session.intake_state.people:
        missing_question = session.intake_state.next_question(destination_names, session.language)
        if missing_question:
            logger.info("Deterministic intake response: %s", missing_question)
            return TurnResult(text=str(missing_question), tool=None)

    # 2. Ask for hotel budget BEFORE asking for dates
    if not session.hotel_pref_state.is_complete:
        # Trip facts (destination/duration/start_date/people) are already locked in
        # by this point (via the with_message call above), but the optional taxonomy
        # fields (companions/pace/day_rhythm/notes) may still be unset if the form's
        # first submission left them blank — the pre-filled form lets a user add them
        # alongside the budget answer on this turn. with_message's own merge rules
        # keep the already-locked required facts untouched (grounded values for an
        # already-set field never win). NOTE: we do NOT call with_message again here
        # to avoid sending the same prompt to the LLM twice in one turn.
        session.hotel_pref_state = session.hotel_pref_state.with_message(user_input)
        missing_pref_question = session.hotel_pref_state.next_question(session.language)
        if missing_pref_question:
            logger.info("Guided hotel-preference response: %s", missing_pref_question)
            return TurnResult(text=str(missing_pref_question), tool=None)

    # 3. Ask for dates if missing (this turn will also pop up the Date Picker via requires_stay_dates)
    if not session.intake_state.is_complete:
        missing_question = session.intake_state.next_question(destination_names)
        if missing_question:
            logger.info("Deterministic intake response (dates): %s", missing_question)
            return TurnResult(text=str(missing_question), tool=None)

    # 4. If we haven't shown hotels yet, force the first recommend_hotels call
    if not session.pending_hotel_selection:
        return _run_recommend_hotels(session)

    # 5. If we already showed hotels, we are in the hotel options chat phase. Let the agent handle questions and re-searches.
    return _run_chat_agent(session, user_input)


def _compact_history(session: TripSession) -> None:
    """Check checkpointer history and compact if too large to save tokens."""
    try:
        state = session.agent.get_state(session.config)
        messages = state.values.get("messages", [])
        if not messages:
            return

        # Rough token approximation (characters / 4)
        total_chars = sum(len(str(getattr(m, "content", str(m)))) for m in messages)
        approx_tokens = total_chars // 4
        
        # Compact if exceeding 70% threshold (e.g., ~5500 tokens)
        if approx_tokens <= 5500:
            return
            
        older_messages = messages[:-4]
        recent_messages = messages[-4:]
        
        if not older_messages:
            return
            
        logger.info(f"History exceeds {approx_tokens} tokens. Compacting...")
        from src.services.llm import get_fast_llm
        from langchain_core.messages import HumanMessage, SystemMessage, RemoveMessage, AIMessage
        
        llm = get_fast_llm(temperature=0.0)
        summary_prompt = (
            "Tóm tắt ngắn gọn nhưng đầy đủ lịch sử cuộc trò chuyện sau. "
            "Ghi nhớ các yêu cầu chính, sở thích, thông tin chuyến đi và quyết định của người dùng.\n"
            f"Lịch sử:\n{older_messages}"
        )
        
        response = llm.invoke([HumanMessage(content=summary_prompt)])
        summary = str(response.content)
        
        # 1. Remove all old messages
        deletes = [RemoveMessage(id=m.id) for m in messages if hasattr(m, "id") and m.id]
        
        # 2. Re-create recent messages without IDs to append them cleanly
        new_messages = [SystemMessage(content=f"Tóm tắt lịch sử cuộc trò chuyện:\n{summary}")]
        for m in recent_messages:
            if isinstance(m, HumanMessage):
                new_messages.append(HumanMessage(content=m.content))
            elif isinstance(m, AIMessage):
                new_messages.append(AIMessage(content=m.content, tool_calls=getattr(m, "tool_calls", [])))
            else:
                new_messages.append(m)
                
        # 3. Update checkpointer state
        session.agent.update_state(session.config, {"messages": deletes + new_messages})
        logger.info("History successfully compacted.")
        
    except Exception as e:
        logger.warning(f"History compaction failed: {e}")


def _run_chat_agent(session: TripSession, user_input: str) -> TurnResult:
    """Invokes the LangGraph supervisor ReAct agent for conversational turns
    (questions, hotel drill-down, complex saved-plan edits). Supports 
    streaming responses directly via callbacks."""
    logger.warning("Inside _run_chat_agent! state keys: %s", session.state.keys())
    logger.warning("Inside _run_chat_agent! pending_hotel_selection is None: %s", session.state.get("pending_hotel_selection") is None)
    for attempt in range(2):
        agent_input = user_input
        
        # Inject context so the chat agent knows the intake is complete if we are in the hotel selection stage.
        # This is needed because Step 2 bypasses the chat agent, leaving its memory empty.
        if not session.initial_plan_complete and session.intake_state.is_complete:
            context_prefix = (
                f"[System: The user has already provided the required info: "
                f"Destination={session.intake_state.destination}, "
                f"Duration={session.intake_state.duration}, "
                f"People={session.intake_state.people}, "
                f"StartDate={session.intake_state.start_date}, "
                f"EndDate={session.intake_state.end_date}. "
                f"Do NOT ask for this info again. You may call recommend_hotels if the user wants to refine their search or budget, or just answer their questions directly.]\n\n"
            )
            agent_input = context_prefix + agent_input
            
        if session.pending_hotel_selection:
            hotel_context = (
                f"[System: You have just presented a list of hotel options to the user. "
                f"Wait for the user to explicitly select one of the options by name or number (e.g. '1', 'the second one', 'Hotel ABC'). "
                f"Once they do, you MUST use the `select_hotel` tool with their exact selection text to build the itinerary. "
                f"DO NOT try to build the itinerary yourself. ONLY use the tool.]\n\n"
            )
            agent_input = hotel_context + agent_input

        if attempt:
            agent_input = (
                f"{agent_input}\n"
                "Trả lời người dùng bằng văn bản tiếng Việt. Không xuất JSON hoặc mô phỏng lời gọi công cụ."
            )
        try:
            # Tools are now module-level and write TripState via Command
            # (Phase 4) — the compiled agent's own checkpointer state is keyed
            # by thread_id and is a SEPARATE store from session.state. Seed
            # the input with the current session.state so a tool call this
            # turn sees up-to-date trip_data/pending_hotel_selection/etc.,
            # then sync the final event back afterward so session.state picks
            # up whatever the tool actually changed. Verified empirically:
            # without the seed, a fresh thread has no TripState keys at all
            config_with_limit = {**session.config, "recursion_limit": 15}
            
            _compact_history(session)
            
            events = session.agent.stream(
                {**session.state, "messages": [("user", agent_input)]},
                config=config_with_limit,
                stream_mode="values",
            )

            final_ai_response = None
            tool_output_response = None
            last_event = None
            for event in events:
                if "messages" not in event:
                    continue
                last_event = event
                latest_message = event["messages"][-1]

                if latest_message.type == "ai" and latest_message.tool_calls:
                    tool_names = ", ".join(tc["name"] for tc in latest_message.tool_calls)
                    logger.info("Delegating to tools: %s", tool_names)
                    logger.warning("AI Message tool_calls: %s", latest_message.tool_calls)
                elif latest_message.type == "tool":
                    if "SYSTEM ERROR:" not in str(latest_message.content):
                        tool_output_response = latest_message.content
                    logger.info("Tool returned: %s", latest_message.name)
                    logger.warning("Tool output: %s...", str(latest_message.content)[:500])
                    
                    # If tool signals anti-loop, abort immediately to prevent LLM from spinning
                    if "ĐỪNG gọi lại" in str(latest_message.content) or "DO NOT CALL IT AGAIN" in str(latest_message.content):
                        logger.warning("Anti-loop signal received from tool. Breaking execution loop.")
                        from src.i18n import t
                        lang = session.state.get("language", "vi")
                        final_ai_response = t(
                            "Xin lỗi, tôi không tìm thấy thông tin này để trả lời bạn.",
                            lang,
                        ) if lang == "vi" else "I'm sorry, I couldn't find this information."
                        break

                if latest_message.type == "ai" and not latest_message.tool_calls:
                    final_ai_response = latest_message.content

            if last_event is not None:
                session.state.update({key: value for key, value in last_event.items() if key != "messages"})
                if "pending_hotel_selection" in last_event and last_event["pending_hotel_selection"]:
                    ph = last_event["pending_hotel_selection"]
                    from src.services.trip_intake import TripIntakeState
                    new_prefs = [p.strip() for p in str(ph.get("preferences_text") or "").split(",") if p.strip()]
                    session.intake_state = TripIntakeState(
                        destination=ph.get("destination") or session.intake_state.destination,
                        duration=ph.get("duration") or session.intake_state.duration,
                        start_date=ph.get("start_date") or session.intake_state.start_date,
                        stay_end_date=ph.get("end_date") or session.intake_state.stay_end_date,
                        people=ph.get("people") or session.intake_state.people,
                        preferences=tuple(new_prefs) if new_prefs else session.intake_state.preferences,
                        companions=session.intake_state.companions,
                        pace=session.intake_state.pace,
                        day_rhythm=session.intake_state.day_rhythm,
                        notes=session.intake_state.notes
                    )
        except Exception as exc:
            if "Recursion limit" in str(exc) or "recursion" in str(exc).lower() or type(exc).__name__ == "GraphRecursionError":
                logger.error("Agent hit recursion limit of 15 loops and was stopped.")
                return TurnResult(
                    text="Xin lỗi, tôi cần thêm thông tin để làm rõ yêu cầu của bạn, hiện tại tôi đang gặp một chút khó khăn khi tự động phân tích.",
                    tool="agent_stream"
                )
            
            logger.exception("Agent provider request failed")
            return TurnResult(
                text=(
                    "SYSTEM ERROR: Mô hình hội thoại không thể xử lý yêu cầu này. "
                    "Vui lòng thử diễn đạt lại yêu cầu cụ thể hơn."
                ),
                tool="agent_stream",
            )

        # Prefer the final AI reply when the agent actually answered the user's
        # question in prose — e.g. "Hotel X does have parking" — over the canned
        # ToolMessage string from recommend_hotels. Fall back to tool_output_response
        # only when the agent produced no non-tool-call prose reply.
        if final_ai_response and not _looks_like_textual_tool_call(final_ai_response):
            logger.info("Final AI Response: %s", final_ai_response)
            # If a tool also ran (e.g. recommend_hotels), keep that state update
            # (already synced via last_event) but return the agent's prose reply.
            return TurnResult(
                text=str(final_ai_response),
                tool="recommend_hotels" if tool_output_response else "agent_stream",
            )
        if tool_output_response:
            logger.info("Final Tool Response Output:\n%s", tool_output_response)
            return TurnResult(text=str(tool_output_response), tool="agent_stream")
        if final_ai_response:
            logger.warning("Discarded textual tool-call JSON from agent (attempt %s)", attempt + 1)
    return TurnResult(
        text="SYSTEM ERROR: Không nhận được phản hồi từ agent.",
        tool="agent_stream",
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
    ) -> None:
        self._sessions: dict[str, TripSession] = {}
        self._registry_lock = threading.Lock()
        self._ttl_seconds = ttl_seconds
        self._cap = cap
        self._persist_hook = persist_hook
        self._load_hook = load_hook
        self._delete_hook = delete_hook

    def create(self) -> TripSession:
        """The only way a session comes into being with a server-generated id."""
        import uuid

        session_id = str(uuid.uuid4())
        with self._registry_lock:
            session = create_chat_session(session_id, persist_hook=self._persist_hook)
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
            if self._load_hook is None:
                return None
            try:
                row = self._load_hook(session_id)
                if row is None:
                    return None
                from src.services.session_store import deserialize

                session = create_chat_session(session_id, persist_hook=self._persist_hook)
                session.state = deserialize(session_id, row.get("context_data"))
                created_at = row.get("created_at")
                if isinstance(created_at, str):
                    try:
                        session.created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
                    except ValueError:
                        logger.warning("Ignoring invalid created_at for session %s", session_id)
                session.last_seen_at = time.time()
                self._sessions[session_id] = session
                return session
            except Exception:
                logger.exception("Unable to rehydrate session %s; treating as unavailable", session_id)
                return None

    def resolve(self, session_id: str) -> TripSession:
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
                session = create_chat_session(session_id, persist_hook=self._persist_hook)
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

    def __len__(self) -> int:
        with self._registry_lock:
            return len(self._sessions)

    def evict_expired(self) -> int:
        """Evict sessions past the TTL, then trim to the size cap by oldest
        last_seen_at (LRU). MUST skip any session whose lock is currently held
        (non-blocking lock.locked() check) — otherwise a session inside a 60s
        tool call could be evicted mid-request, and the next request for the same
        id builds a fresh session that runs concurrently with the in-flight one.
        """
        now = time.time()
        evicted = 0
        with self._registry_lock:
            expired_ids = [
                session_id
                for session_id, session in self._sessions.items()
                if now - session.last_seen_at > self._ttl_seconds and not session.lock.locked()
            ]
            for session_id in expired_ids:
                del self._sessions[session_id]
                evicted += 1

            if len(self._sessions) > self._cap:
                evictable = sorted(
                    (session for session in self._sessions.values() if not session.lock.locked()),
                    key=lambda session: session.last_seen_at,
                )
                overflow = len(self._sessions) - self._cap
                for session in evictable[:overflow]:
                    del self._sessions[session.session_id]
                    evicted += 1

        return evicted

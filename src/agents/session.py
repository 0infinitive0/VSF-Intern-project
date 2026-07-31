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
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.agents.graph import build_trip_agent
from src.agents.nodes.intake import is_finalization_request
from src.services.hotel_selection import (
    HotelPreferenceState,
    rank_hotel_candidates,
    select_hotel_candidates,
)
from src.services.trip_edit_planner import TripEditPlan, TripEditPlanError, plan_trip_edit
from src.services.trip_formatter import format_hotel_options, format_trip_response_from_json
from src.services.trip_intake import (
    TripIntakeState,
    _llm_extract_intake_facts,
    _match_known_destination,
)
from src.services.trip_planner import (
    _current_trip_parameters,
    _get_destination_id,
    _get_destination_names,
    _persist_itinerary_metadata,
    apply_trip_edit_plan,
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


def derive_stage(result: TurnResult) -> str:
    """Derive the `stage` value from a TurnResult.

    Keeps stage derivation in one place — do NOT re-derive it in the endpoint
    handler or per branch of process_chat_turn.
    """
    if result.text.startswith("SYSTEM ERROR:"):
        return "error"
    return _STAGE_MAP.get(result.tool, "intake")


@dataclass
class TripSession:
    """Per-conversation state — one instance per terminal run, or per web
    session_id. Mutated in place by process_chat_turn as the conversation
    progresses through intake -> hotel preferences -> recommend/select -> agent.

    Absorbs the former `ChatSession`; `trip_data` and `pending_hotel_selection`
    replace the two module-level JSON files current_trip_plan.json and
    pending_hotel_selection.json so two sessions never share state.
    """

    session_id: str
    agent: Any
    config: dict
    tools: Any = None  # SessionTools — set by create_chat_session via build_trip_agent
    intake_state: TripIntakeState = field(default_factory=TripIntakeState)
    hotel_pref_state: HotelPreferenceState = field(default_factory=HotelPreferenceState)
    initial_plan_complete: bool = False
    planning_new_trip: bool = False
    pending_trip_edit_request: str | None = None
    trip_data: dict[str, Any] | None = None
    pending_hotel_selection: dict[str, Any] | None = None
    persist_hook: Callable[[TripSession], None] | None = None
    created_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


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


def _save_trip_data(session: TripSession, trip_data: dict[str, Any], *, persist_to_supabase: bool = True) -> None:
    """Pure in-memory mutation of session.trip_data, plus the session's optional
    persistence hook. `persist_to_supabase` controls the separate Supabase
    itinerary-metadata upsert — unrelated to persist_hook, which is about the
    two legacy JSON files the CLI still writes."""
    session.trip_data = trip_data
    if persist_to_supabase:
        _persist_itinerary_metadata(trip_data)
    if session.persist_hook:
        session.persist_hook(session)


def _save_pending_hotel_selection(session: TripSession, payload: dict[str, Any]) -> None:
    """Persist the hotel options just shown to the user, so the next chat turn can
    resolve their reply (a rank number or a name) back to one of them."""
    session.pending_hotel_selection = payload
    if session.persist_hook:
        session.persist_hook(session)


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
    # A shown hotel list is awaiting a pick, and outranks everything else: the
    # very next turn is routed to select_hotel regardless of session state.
    if session.pending_hotel_selection is not None:
        pending = session.pending_hotel_selection or {}
        chips: list[dict[str, str]] = []
        for index, option in enumerate(pending.get("options") or [], start=1):
            name = str(option.get("name") or "").strip()
            if not name:
                continue
            chips.append({"label": f"{index}. {name}", "value": str(index)})
        return chips

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


def _normalize_intent_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.replace("Đ", "D").replace("đ", "d"))
    return "".join(character for character in decomposed if not unicodedata.combining(character)).casefold()


def _new_trip_signal(message: str) -> str | None:
    """Return a conservative signal for starting a separate trip.

    A strong signal explicitly says the trip/plan is new. A destination
    signal still requires intake to ground a real destination before the
    saved Draft is bypassed.
    """
    normalized = _normalize_intent_text(message)
    if re.search(r"\b(?:chuyen di|lich trinh|ke hoach)(?: du lich)? moi\b", normalized):
        return "strong"
    # "ngày N" marks an edit scope ("đổi khách sạn ngày 2"), but the same letters
    # appear in every ordinary new-trip sentence: "3 ngày 2 người" normalizes to
    # "3 ngay 2 nguoi", where the N is the head count. Without these guards the
    # most common way to start a trip is read as editing day 2 of the saved plan.
    # A duration reads as "<digit> ngày"; a scope reads as "ngày <digit>" with no
    # digit before it and no unit word after it.
    day_scope = r"(?<!\d\s)\bngay\s+\d+\b(?!\s*(?:nguoi|dem|tuan|thang))"
    if re.search(r"\b(?:doi|sua|thay|them|bo|xoa)\b", normalized) or re.search(day_scope, normalized):
        return None
    # Any ordinary "let's go somewhere" phrasing counts. This stays safe because it
    # is only a *candidate*: _begin_new_trip_if_requested still refuses unless intake
    # grounds a real destination, and the edit verbs / day scopes above already
    # returned. Requiring the exact words "muốn đi du lịch" missed the most common
    # opener of all — "đi Đà Nẵng 3 ngày 2 người".
    if re.search(r"\b(?:di|du lich|len ke hoach|lap ke hoach|len lich trinh)\b", normalized):
        return "destination"
    return None


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


_OTHER_INTENT_WORDS = re.compile(
    r"\b(?:doi|sua|thay|them|bo|xoa|chot|xac nhan|hoan tat|tai sao|vi sao|sao lai|the nao|gi vay)\b"
)


def _is_hotel_choice_attempt(user_input: str) -> bool:
    """Whether a reply that failed to resolve was still *trying* to name a hotel.

    True keeps the list up and re-asks (a typo'd name, an out-of-range number).
    False means the user has moved on, and holding the list would trap them.
    """
    stripped = user_input.strip()
    if not stripped:
        return True
    # A bare number is always an attempt, even out of range — never read "3" as a
    # topic change just because the list is shorter than that.
    if stripped.isdigit():
        return True
    if is_finalization_request(user_input):
        return False
    normalized = _normalize_intent_text(user_input)
    if _OTHER_INTENT_WORDS.search(normalized):
        return False
    if _new_trip_signal(user_input) is not None:
        return False
    return True


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


def execute_trip_edit_request(session: TripSession, modification_request: str, plan: TripEditPlan) -> str | None:
    """Execute an already validated LLM edit plan against the saved Draft.

    Called directly from process_chat_turn, not by the LLM — that is why it
    lives here rather than as an agent-visible @tool.
    """
    if session.trip_data is None:
        return "SYSTEM ERROR: Chưa có kế hoạch chuyến đi để chỉnh sửa."
    current_data = session.trip_data

    saved_itinerary = (current_data.get("itineraries") or [{}])[0]
    if isinstance(saved_itinerary, dict) and str(saved_itinerary.get("status") or "").casefold() == "finalized":
        return "Kế hoạch đã xác nhận không thể chỉnh sửa. Hãy tạo một kế hoạch mới nếu cần thay đổi."
    if plan.decision == "clarify":
        return plan.clarification_question or "Bạn muốn chỉnh sửa phần nào của lịch trình?"
    if plan.decision == "not_edit":
        return None

    hotel_change = next((operation for operation in plan.operations if operation.operation == "change_hotel"), None)
    if hotel_change:
        try:
            destination, duration, people, preferences = _current_trip_parameters(current_data)
            destination_id = str(saved_itinerary.get("destination_id") or _get_destination_id(destination) or "")
            if not destination or not destination_id:
                raise ValueError("Kế hoạch hiện tại thiếu điểm đến để đổi khách sạn.")
            hotel_query = hotel_change.hotel_query or modification_request
            options = rank_hotel_candidates(
                select_hotel_candidates(destination, destination_id, people, hotel_query=hotel_query)
            )
            if not options:
                raise ValueError(f"Không tìm thấy khách sạn phù hợp tại {destination}.")
            _save_pending_hotel_selection(
                session,
                {
                    "mode": "change_hotel",
                    "destination": destination,
                    "destination_id": destination_id,
                    "duration": duration,
                    "people": people,
                    "preferences_text": preferences,
                    "hotel_query": hotel_query,
                    "planning_constraints": dict(saved_itinerary.get("planning_constraints") or {}),
                    "created_at": datetime.now().isoformat(),
                    "options": [data for data, _candidate in options],
                },
            )
            return format_hotel_options(options)
        except Exception as exc:
            logger.exception("Failed to prepare hotel change")
            return f"SYSTEM ERROR: {exc}"

    try:
        adjustments = apply_trip_edit_plan(current_data, plan)
        current_data.setdefault("adjustments", []).extend(adjustments)
        _save_trip_data(session, current_data)
        logger.info("Applied LLM edit plan: %s", [operation.operation for operation in plan.operations])
        return format_trip_response_from_json(current_data)
    except Exception as exc:
        logger.exception("Failed to apply LLM edit plan")
        return f"SYSTEM ERROR: {exc}"


def process_chat_turn(session: TripSession, user_input: str) -> TurnResult:
    """Handle exactly one chat turn and return a TurnResult. Mutates `session`
    in place. Callers own their own input loop / HTTP request cycle — this
    function never blocks on input() and never prints.

    The returned TurnResult.tool records which tool actually ran so that the
    HTTP layer can derive `stage` without re-implementing routing logic. The
    CLI caller uses .text directly.
    """
    logger.info("User Input: %s", user_input)
    session.last_seen_at = time.time()

    if session.pending_hotel_selection is not None:
        tool_response = session.tools.select_hotel.invoke({"selection": user_input})
        logger.info("Hotel selection response: %s", tool_response)
        # select_hotel clears the pending selection once it resolves a hotel, so
        # that clearing — not the wording of the reply — is what says it failed.
        picked = session.pending_hotel_selection is None
        if picked:
            session.initial_plan_complete = not str(tool_response).startswith("SYSTEM ERROR:")
            if session.initial_plan_complete:
                session.planning_new_trip = False
            return TurnResult(text=str(tool_response), tool="select_hotel")

        if _is_hotel_choice_attempt(user_input):
            return TurnResult(text=str(tool_response), tool="select_hotel")

        # Not a pick and not an attempt at one. Re-asking here is what trapped
        # people: with a list pending, every later message was read as a choice,
        # so "chốt lịch trình" and "thêm quán cà phê ngày 2" both came back as
        # "mình chưa xác định được khách sạn", forever. Drop the list and let the
        # message be handled for what it actually is.
        logger.info("Reply is not a hotel choice; dropping the pending list")
        _clear_pending_hotel_selection(session)

    if session.trip_data is not None and is_finalization_request(user_input):
        tool_response = session.tools.finalize_trip_plan.invoke({})
        logger.info("Finalization response: %s", tool_response)
        session.initial_plan_complete = not str(tool_response).startswith("SYSTEM ERROR:")
        return TurnResult(text=str(tool_response), tool="finalize_trip_plan")

    has_saved_plan = session.trip_data is not None
    if has_saved_plan and not session.planning_new_trip:
        if not _begin_new_trip_if_requested(session, user_input):
            unsupported_reply = _unsupported_destination_reply(user_input)
            if unsupported_reply:
                logger.info("New-trip request names an unsupported destination")
                return unsupported_reply

    is_saved_plan_edit = has_saved_plan and not session.planning_new_trip
    if is_saved_plan_edit:
        try:
            current_data = session.trip_data
            planner_request = user_input
            if session.pending_trip_edit_request:
                planner_request = f"{session.pending_trip_edit_request}\nLàm rõ của người dùng: {user_input}"
            edit_plan = plan_trip_edit(planner_request, current_data)
        except TripEditPlanError as exc:
            logger.warning("Saved-trip edit planner failed safely: %s", exc)
            return "SYSTEM ERROR: Không thể hiểu an toàn yêu cầu chỉnh sửa này. Vui lòng diễn đạt cụ thể hơn."

        if edit_plan.decision == "clarify":
            session.pending_trip_edit_request = planner_request
            return edit_plan.clarification_question or "Bạn muốn chỉnh sửa phần nào của lịch trình?"
        session.pending_trip_edit_request = None
        if edit_plan.decision == "apply":
            tool_response = execute_trip_edit_request(session, user_input, edit_plan)
            logger.info("LLM planned modification response: %s", tool_response)
            reply_text = tool_response or "SYSTEM ERROR: Không thể áp dụng yêu cầu chỉnh sửa này."
            return TurnResult(text=str(reply_text), tool="execute_trip_edit_request")

    if not session.initial_plan_complete and not is_saved_plan_edit:
        if not session.intake_state.is_complete:
            destination_names = _get_destination_names()
            session.intake_state = session.intake_state.with_message(user_input, destination_names)
            missing_question = session.intake_state.next_question(destination_names)
            if missing_question:
                logger.info("Deterministic intake response: %s", missing_question)
                return TurnResult(text=str(missing_question), tool=None)

            # Trip facts just became complete THIS turn (consumed by intake_state
            # above) — ask the first hotel-preference question next turn, rather
            # than also feeding this same input into hotel_pref_state right now.
            logger.info("Trip intake complete; asking hotel budget preference")
            return TurnResult(text=str(session.hotel_pref_state.next_question()), tool=None)

        if not session.hotel_pref_state.is_complete:
            session.hotel_pref_state = session.hotel_pref_state.with_message(user_input)
            missing_pref_question = session.hotel_pref_state.next_question()
            if missing_pref_question:
                logger.info("Guided hotel-preference response: %s", missing_pref_question)
                return TurnResult(text=str(missing_pref_question), tool=None)

        verified_arguments = {
            **session.intake_state.tool_arguments(),
            **session.hotel_pref_state.tool_arguments(),
        }
        logger.info("Deterministic intake complete: %s", verified_arguments)
        tool_response = session.tools.recommend_hotels.invoke(verified_arguments)
        logger.info("Final Tool Response Output:\n%s", tool_response)
        return TurnResult(text=str(tool_response), tool="recommend_hotels")

    for attempt in range(2):
        agent_input = user_input
        if attempt:
            agent_input = (
                f"{user_input}\n"
                "Trả lời người dùng bằng văn bản tiếng Việt. Không xuất JSON hoặc mô phỏng lời gọi công cụ."
            )
        try:
            events = session.agent.stream(
                {"messages": [("user", agent_input)]},
                config=session.config,
                stream_mode="values",
            )

            final_ai_response = None
            tool_output_response = None
            for event in events:
                if "messages" not in event:
                    continue
                latest_message = event["messages"][-1]

                if latest_message.type == "ai" and latest_message.tool_calls:
                    tool_names = ", ".join(tc["name"] for tc in latest_message.tool_calls)
                    logger.info("Delegating to tools: %s", tool_names)
                elif latest_message.type == "tool":
                    if "SYSTEM ERROR:" not in str(latest_message.content):
                        tool_output_response = latest_message.content
                    logger.info("Tool returned: %s", latest_message.name)

                if latest_message.type == "ai" and not latest_message.tool_calls:
                    final_ai_response = latest_message.content
        except Exception:
            logger.exception("Agent provider request failed")
            return TurnResult(
                text=(
                    "SYSTEM ERROR: Mô hình hội thoại không thể xử lý yêu cầu này. "
                    "Vui lòng thử diễn đạt lại yêu cầu cụ thể hơn."
                ),
                tool="agent_stream",
            )

        if tool_output_response:
            logger.info("Final Tool Response Output:\n%s", tool_output_response)
            return TurnResult(text=str(tool_output_response), tool="agent_stream")
        if final_ai_response and not _looks_like_textual_tool_call(final_ai_response):
            logger.info("Final AI Response: %s", final_ai_response)
            return TurnResult(text=str(final_ai_response), tool="agent_stream")
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
    ) -> None:
        self._sessions: dict[str, TripSession] = {}
        self._registry_lock = threading.Lock()
        self._ttl_seconds = ttl_seconds
        self._cap = cap
        self._persist_hook = persist_hook

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

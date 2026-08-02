"""Pure-ish routing decision layer extracted from `process_chat_turn`'s cascade.

`decide_route_by_rules` reproduces today's cascade conditions, in priority
order, returning a route label instead of executing it directly. It becomes
Phase 2's deterministic fallback when the LLM supervisor is unavailable.

Not fully pure: distinguishing `new_trip` from `edit_draft` on a *weak*
new-trip signal (a saved plan exists, and the message doesn't explicitly say
"chuyến đi mới") requires checking whether the message names a *known*
destination. That check already goes through the same intake-extraction LLM
call this codebase uses everywhere else (`TripIntakeState.with_message`),
mirroring `_begin_new_trip_if_requested`'s existing behavior in
`src/agents/session.py`. This is a deliberate, accepted deviation from full
purity — see plan `260731-1508-supervisor-react-router-for-chat-turn`,
Phase 1 Decisions. It only fires on the weak-signal path; a strong signal
("chuyến đi mới") or no signal at all never touches the LLM here.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, get_args

from src.agents.nodes.intake import is_finalization_request
from src.services.hotel_selection import HotelPreferenceState
from src.services.trip_intake import TripIntakeState
from src.services.trip_planner import _get_destination_names

if TYPE_CHECKING:
    from src.agents.state import TripState

Route = Literal["select_hotel", "finalize", "new_trip", "edit_draft", "intake", "chat"]
_VALID_ROUTES = frozenset(get_args(Route))


@dataclass(frozen=True)
class RouteContext:
    """Everything the router may look at. Deliberately excludes venue data,
    hotel candidates, and itinerary items — a router cannot select a place."""

    has_pending_hotel_selection: bool
    has_trip_data: bool
    is_trip_finalized: bool
    initial_plan_complete: bool
    planning_new_trip: bool
    intake_complete: bool
    hotel_prefs_complete: bool
    has_pending_edit_clarification: bool


def route_context_from_state(state: TripState) -> RouteContext:
    """Reads only the state dict — no session object, no runtime fields.
    `intake`/`hotel_prefs` are reconstructed via `from_dict` to reuse
    `is_complete`'s existing logic rather than duplicating that predicate
    against the raw dict."""
    trip_data = state["trip_data"]
    itineraries = (trip_data or {}).get("itineraries") or [{}]
    is_trip_finalized = itineraries[0].get("status") == "Finalized"
    intake = TripIntakeState.from_dict(state["intake"])
    hotel_prefs = HotelPreferenceState.from_dict(state["hotel_prefs"])
    return RouteContext(
        has_pending_hotel_selection=state["pending_hotel_selection"] is not None,
        has_trip_data=trip_data is not None,
        is_trip_finalized=is_trip_finalized,
        initial_plan_complete=state["initial_plan_complete"],
        planning_new_trip=state["planning_new_trip"],
        intake_complete=intake.is_complete,
        hotel_prefs_complete=hotel_prefs.is_complete,
        has_pending_edit_clarification=state["pending_trip_edit_request"] is not None,
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


def _new_trip_would_begin(user_input: str) -> bool:
    """Mirrors `_begin_new_trip_if_requested`'s decision without mutating
    session state — used only to label the route new_trip vs edit_draft."""
    signal = _new_trip_signal(user_input)
    if signal is None:
        return False
    if signal == "strong":
        return True
    destination_names = _get_destination_names()
    fresh_intake = TripIntakeState().with_message(user_input, destination_names)
    return bool(fresh_intake.destination)


def decide_route_by_rules(context: RouteContext, user_input: str) -> Route:
    """Today's `process_chat_turn` cascade conditions, verbatim in priority and
    outcome, returning a route label instead of executing.

    Priority: pending hotel > finalize > new-trip signal > saved-plan edit >
    intake/hotel-prefs gate > chat fallback (matches `session.py:456-546`
    pre-refactor).
    """
    if context.has_pending_hotel_selection:
        return "select_hotel"

    if context.has_trip_data and is_finalization_request(user_input):
        return "finalize"

    if context.has_trip_data and not context.planning_new_trip:
        if _new_trip_would_begin(user_input):
            return "new_trip"
        return "edit_draft"

    if not context.initial_plan_complete:
        return "intake"

    return "chat"


_IMPOSSIBLE: dict[Route, Callable[[RouteContext], bool]] = {
    "edit_draft": lambda ctx: not ctx.has_trip_data,
    "finalize": lambda ctx: not ctx.has_trip_data or ctx.is_trip_finalized,
    "select_hotel": lambda ctx: not ctx.has_pending_hotel_selection,
}


def validate_route(proposed: str, context: RouteContext) -> Route | None:
    """Validate the supervisor's proposed route label like every other LLM
    output in this codebase: it's a proposal, not a fact. None means unusable —
    the caller falls back to `decide_route_by_rules`."""
    if proposed not in _VALID_ROUTES:
        return None
    is_impossible = _IMPOSSIBLE.get(proposed)  # type: ignore[arg-type]
    if is_impossible is not None and is_impossible(context):
        return None
    return proposed  # type: ignore[return-value]

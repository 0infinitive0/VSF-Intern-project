"""Orchestration-layer routing tables: worker names, delegation order, and
the possibility guard. `domain/travel_state.py` returns `Workflow` labels
(`detect_impact`) and must stay ignorant of graph node names (Phase 3
purity test) — that mapping lives here instead.
"""

from __future__ import annotations

from collections.abc import Callable

from src.agents.graph.state import TravelGraphState
from src.domain.travel_state import Workflow

WORKFLOW_TO_WORKER: dict[Workflow, str] = {
    "hotel": "hotel_node",
    "itinerary": "itinerary_node",
    "itinerary_day": "itinerary_node",  # same worker, narrower scope in state
}

# Fixed order when several workflows are impacted: the hotel anchors the
# itinerary, so rebuilding the itinerary first would schedule around a hotel
# about to change.
WORKER_ORDER: tuple[str, ...] = ("hotel_node", "itinerary_node", "booking_node", "qa_node")


def _never(_state: TravelGraphState) -> bool:
    return False


# Structured output guarantees a valid *label*, not a *possible action* —
# ported forward from the legacy router's `_IMPOSSIBLE`
# (`routing_decision.py:174-177`).


def _no_destination(state: TravelGraphState) -> bool:
    """No worker can act on a trip with no destination. `ask_slot` normally
    gates this long before the supervisor sees the turn; this is the
    backstop for the paths that skip it."""
    return not bool((state.get("travel_state") or {}).get("destination"))


def requires_existing_trip(state: TravelGraphState) -> bool:
    """`itinerary_node` is an EDITOR, not a builder.

    Every action it has — `rebuild_days`, `edit_item`, `lock_days` — operates
    on a `trip_data` that already exists; none of them can create one. The
    trip is created by `hotel_node` when the user picks a hotel
    (`_handle_hotel_selection` -> `build_selected_hotel_trip`, which builds
    the hotel *and* the whole itinerary in one pass).

    That ordering is a causal constraint of the product, not a preference:
    the itinerary is scheduled around the hotel's location, so it cannot be
    built before we know where the user is staying. `WORKER_ORDER` encodes
    the same reason.

    Without this check, a single message setting destination/dates/people/
    preferences at once (the common first-intake turn) impacts both the
    `hotel` and `itinerary` workflows, so `itinerary_node` looked "possible"
    purely from `destination` and became a supervisor-LLM coin flip against
    `hotel_node` — reported bug: the LLM sometimes picked `itinerary_node`
    first, which bailed immediately with nothing to show, forcing the user
    to resend the identical message.
    """
    return not bool(state.get("trip_data"))


_IMPOSSIBLE: dict[str, Callable[[TravelGraphState], bool]] = {
    "itinerary_node": lambda s: _no_destination(s) or requires_existing_trip(s),
    "booking_node": lambda s: True,  # blocked until the booking plan lands
}


def is_impossible(worker: str, state: TravelGraphState) -> bool:
    return _IMPOSSIBLE.get(worker, _never)(state)


def can_list_nearby(state: TravelGraphState) -> bool:
    """`list_nearby` is the one `itinerary_node` action `requires_existing_trip`
    is too strict for.

    That guard exists because the node's other three actions EDIT a trip and
    so cannot run before one exists. `list_nearby` edits nothing — it needs
    only a hotel to measure from, and the numbered shortlist on screen before
    the pick is full of them. Gating it on `is_impossible` therefore blocked
    the one stage where "quanh khách sạn số 1 có gì?" is the most useful
    question a user can ask: while they are still deciding between the cards.

    A destination is still required (`search_attraction_candidates` filters
    by it), and so is at least one shown card — with neither trip nor
    shortlist there is nothing to center a radius on, and the turn falls
    through to `qa_node` exactly as it did before.
    """
    if _no_destination(state):
        return False
    if not requires_existing_trip(state):
        return True
    # Imported here, not at module scope: `agents.tools` pulls in the service
    # layer (Supabase clients, the amenity catalog), and this module is
    # imported by the graph builder itself.
    from src.agents.tools.shown_hotels import shown_hotel_options

    return bool(shown_hotel_options(state))


def needs_trip_first(state: TravelGraphState) -> bool:
    """The turn asked for itinerary work before a trip exists.

    This is the one reason `itinerary_node` is impossible that has an
    obvious next step rather than being a dead end: the trip is created by
    picking a hotel, so the turn should go do that (see
    `requires_existing_trip`). The supervisor acts on this instead of
    delegating to nobody and answering with nothing.

    Narrow on purpose: a missing *destination* is `ask_slot`'s job, and
    redirecting that turn would only produce `hotel_node`'s own "no
    destination" defensive reply.
    """
    if "itinerary_node" not in (state.get("pending_tasks") or []):
        return False
    if _no_destination(state) or not requires_existing_trip(state):
        return False
    return not is_impossible("hotel_node", state)


def all_tasks_done(state: TravelGraphState) -> bool:
    """Plain predicate on a conditional edge — no LLM. `True` once every
    worker the current turn's applied patch impacted has reported a
    result."""
    return not state.get("pending_tasks")


def route_after_itinerary_node(state: TravelGraphState) -> str:
    """`itinerary_node`'s own completion edge, `all_tasks_done`, still
    decides `supervisor` vs. moving on -- this only picks what "moving on"
    means. `budget_check` re-plans (hotel search + unlocked-day rebuild)
    whenever `budget.trip_total` is set, regardless of whether THIS turn
    wrote anything: harmless after a real edit, but for the read-only
    `list_nearby` turn (`supervisor.py`'s `read_only_intent_nearby` source)
    it does two things a read-only turn must never do -- silently mutate
    the plan, and overwrite `task_results[-1]`, which is where
    `suggested_places_from_task_results` (`response_payload.py`) reads the
    pins this turn exists to produce. Routing straight to `respond` instead
    mirrors `qa_node`'s own edge (`graph.py`: "read-only: no budget or
    orchestration follow-up")."""
    if not all_tasks_done(state):
        return "supervisor"
    if state.get("routing_source") == "read_only_intent_nearby":
        return "respond"
    return "budget_check"


def route_scope_guard(state: TravelGraphState) -> str:
    """`scope_guard` blocked a jailbreak attempt (`detect_jailbreak`,
    `JAILBREAK_GUARD_MODE=block`) -> skip the whole patch pipeline and go
    straight to `respond`, mirroring the legacy plane's behavior of never
    reaching a tool/LLM call for a blocked input."""
    return "blocked" if state.get("jailbreak_blocked") else "proceed"


def is_intake_question(state: TravelGraphState) -> bool:
    """True when the patch pipeline concluded — not merely guessed — that
    this turn's message is a genuine read-only question
    (`intent == "general_question"` with `extraction_failed` false). Shared
    by `route_ask_slot` (routes to `intake_qa`) and `ask_slot`
    (`nodes/ask_slot.py::_context_line`, which must not blame the user for
    "not answering" a slot when they asked a question instead — a question
    is not a failed answer attempt).
    """
    return state.get("intent") == "general_question" and not state.get("extraction_failed")


# Only the two intents whose empty-patch case is genuinely "a value is
# missing". `hotel_search`, `select_hotel`, and `finalize` all have
# legitimate empty-patch semantics that already work today (a re-run
# search, a hotel pick `hotel_node` resolves, a confirm that needs a
# worker) -- excluding them structurally means their behavior never depends
# on `patch_reason` being labeled correctly.
_INCOMPLETE_EDIT_INTENTS = frozenset({"update_itinerary", "update_trip"})


def is_incomplete_edit(state: TravelGraphState) -> bool:
    """True when the turn was understood as an edit but committed nothing,
    and no worker is going to speak in its place.

    Three guards stand between this and over-triggering on a turn that
    already worked (a re-run search, a hotel pick, a confirm):

    1. Structural: only `_INCOMPLETE_EDIT_INTENTS` qualifies. `hotel_search`
       / `select_hotel` / `finalize` never reach this function's last line
       at all.
    2. This function: `patch_reason == "missing_value"`, the extractor's own
       account of why the patch is empty, not an inference drawn from it
       here. `""` (absent or unrecognized) is the fail-open value and
       routes as this turn does today.
    3. Downstream, once this returns True and `intake_qa` actually runs:
       `route_intake_qa`'s safety net, for a decline or a failure.

    `pending_tasks` — not `applied_changes` — is the "a worker will reply"
    signal: `selected_hotel_id` seeds `hotel_node` with zero applied changes
    (`apply_patch.py`), and that turn already has a reply coming.

    `extraction_failed` excludes a provider outage, the same way
    `is_intake_question` already does: a garbled response is not a user
    asking for something.
    """
    if state.get("pending_tasks") or state.get("extraction_failed"):
        return False
    if state.get("patch"):
        return False
    if state.get("intent") not in _INCOMPLETE_EDIT_INTENTS:
        return False
    return state.get("patch_reason") == "missing_value"


def route_intake_qa(state: TravelGraphState) -> str:
    """`intake_qa` has two callers, and "no answer" means something
    different to each.

    On the intake branch (`missing_slots` non-empty) a `NO_ANSWER` still has
    to reach `respond`, because `ask_slot` left a pending question that must
    be delivered either way.

    Post-intake there is no pending question, so an absent answer would
    leave `respond` with nothing at all: `_compose(None, None)` is `None`,
    no worker ran, and the turn ends on the generic-ack ERROR branch.
    `supervisor` is where that turn would have gone without this whole
    feature, so it is both the safe fallback and the honest one.

    This is a safety net, not the mechanism: `is_incomplete_edit` already
    decided, deterministically, that this turn is worth asking about.
    Reaching the `supervisor` leg means the node declined or failed after
    that.
    """
    if state.get("missing_slots"):
        return "respond"
    return "respond" if state.get("intake_answer") else "supervisor"


def route_ask_slot(state: TravelGraphState) -> str:
    """`"ask"` routes through `respond` rather than straight to `END` so the
    frozen `PlannerChatResponse` shape is always built.

    Phase 15's third branch: a required slot is still missing AND
    `is_intake_question` — `intake_qa` answers it and `ask_slot`'s question
    still follows in the same reply. A parse failure or an empty message
    falls through to `"ask"` instead, so a provider outage is never sent to
    an LLM to answer confidently.

    Phase 16: once no slot is missing, `is_incomplete_edit` gets the same
    branch for a different reason — not a question to answer, but a value
    to ask for so the turn doesn't silently commit nothing. The
    `missing_slots` check stays first either way, which keeps `ask_slot`
    the sole owner of the intake gate.
    """
    if not state.get("missing_slots"):
        return "intake_qa" if is_incomplete_edit(state) else "supervisor"
    if is_intake_question(state):
        return "intake_qa"
    return "ask"


def route_supervisor(state: TravelGraphState) -> str:
    """The supervisor node already decided; this edge only reads its
    decision back. `next_worker` is always one of the five conditional-edge
    keys the supervisor node itself is allowed to return."""
    return state.get("next_worker") or "respond"

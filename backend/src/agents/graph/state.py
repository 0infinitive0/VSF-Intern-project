"""`TravelGraphState` — execution state for the graph control plane.

Deliberately small (doc §9): ids, messages, the patch pipeline's working
data, and the supervisor loop's bookkeeping. The **business** state is the
Phase 3 `TravelState` (`src/domain/travel_state.py`), carried here as a
plain dict under `travel_state` and loaded/committed by `load_context` /
`apply_patch` — this TypedDict carries execution, not truth.

Every field here is read with `.get(...)` by nodes, never `[...]`, because
the checkpointer only has values for keys a previous node actually returned
(see `nodes/load_context.py`'s docstring for why the very first turn on a
thread has none of them yet).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class TravelGraphState(TypedDict, total=False):
    # --- identity -----------------------------------------------------
    session_id: str
    language: str

    # --- messages -------------------------------------------------------
    messages: Annotated[list, add_messages]

    # --- business state (Phase 3 TravelState, via to_dict/from_dict) ----
    travel_state: dict[str, Any]

    # --- patch pipeline (Phase 6/3) --------------------------------------
    patch: list[dict[str, Any]]  # proposed {path, operation, value} changes
    # extract_patch's classification. Selects no WORKER (`detect_impact` +
    # `WORKFLOW_TO_WORKER` does that, off the validated patch) but does
    # separate read-only Q&A from state-changing turns on one routing edge:
    # `route_ask_slot`'s "ask" vs "intake_qa" branch (Phase 15). See
    # plan.md's "Decided while planning" table.
    intent: str
    proposed_travel_state: dict[str, Any]  # validate_patch's output; apply_patch commits it
    applied_changes: list[dict[str, Any]]
    # The subset of `applied_changes` that OVERWROTE a value the user had
    # already given ("đi Hà Nội" -> "đi Nha Trang"), as canonical paths.
    # Computed by `apply_patch`, which is the only node holding both the
    # before-state and the committed one. A first-time answer is deliberately
    # absent: nothing was revised, and `ask_slot` moving on to the next
    # question is already the acknowledgement.
    revised_slots: list[str]
    rejected_changes: list[dict[str, Any]]
    # Phrases stated this turn that could not bind to an approved catalog ID.
    # Turn-scoped: hotel_node surfaces them once; they never enter travel_state.
    unresolved_amenities: list[str]
    ambiguous_amenities: list[dict[str, Any]]
    impacted_workflows: list[str]  # Workflow labels from detect_impact()
    # Raw text of a `Command(resume=...)` reply that did NOT resolve the
    # ambiguity `interrupt()` paused on (Phase 7) -- `_run_turn_via_graph`
    # (api/routes.py) re-runs it as a normal fresh turn instead of losing
    # it. None on every turn that wasn't a resume, or that resolved cleanly.
    unresolved_resume_text: str | None

    # --- slot gate (Phase 7) --------------------------------------------
    missing_slots: list[str]
    next_question: str | None

    # --- intake QA escape (Phase 15) -------------------------------------
    # `extract_patch` sets this True on either of its two fallback returns
    # (unparseable/exhausted-retry, or an empty message) -- separates "the
    # extractor failed" from "the extractor ran and concluded this message
    # changes nothing", both of which otherwise collapse to
    # `intent == "general_question"`. Turn-scoped; reset by `load_context`.
    extraction_failed: bool
    # Why this turn's patch is empty, when it is -- `extract_patch`'s own
    # account, not an inference drawn from it later. Meaningful only
    # alongside an empty `patch`; "" whenever the model omitted it or named
    # something unrecognized. Turn-scoped; reset by `load_context`.
    patch_reason: str
    # `extract_patch`'s read-only-listing hint: the user wants to SEE places
    # near the hotel, not change anything. Deliberately NOT an `intent`
    # value -- `intent` never selects a worker (see this file's `intent`
    # comment and extract_patch.py's docstring), and widening `_INTENTS`
    # would drag `_INCOMPLETE_EDIT_INTENTS` and the read-only rescue gate
    # in with it. `supervisor` reads this to send the turn to
    # `itinerary_node`'s read-only `list_nearby` action instead of
    # `qa_node`, whose tools cannot write the map's `suggested_places` at
    # all (structurally -- see `qa_node.py`'s QAState docstring).
    # Turn-scoped; reset by `load_context`.
    asks_nearby_places: bool
    # The day `extract_patch` is, this turn, asking `intake_qa` to clarify
    # a theme for (Phase 16) -- `None` otherwise. Deliberately NOT
    # turn-scoped and NOT reset by `load_context`, same convention as
    # `missing_slots`: it has to survive from the end of the clarify turn
    # into the START of the very next one, where `extract_patch` reads it
    # back as a fallback day scope for a bare reply ("biển") that names no
    # day itself. `extract_patch` is the sole writer on both ends and
    # always overwrites it with the ONE day the current message itself
    # named (or clears it), never the carried-over value, so an unrelated
    # later turn can't renew it. Known gap: a few graph paths never call
    # `extract_patch` at all (a blocked turn, a hotel pick, an interrupt
    # resume), so a day can still outlive more than one turn across those.
    # See extract_patch.py's module docstring.
    pending_clarify_day: int | None
    # `intake_qa`'s answer, kept out of `task_results` because `intake_qa`
    # is not a worker and consumes no `pending_tasks` entry. Turn-scoped;
    # reset by `load_context`.
    intake_answer: str | None

    # --- scope guard -------------------------------------------------------
    jailbreak_blocked: bool

    # --- supervisor loop --------------------------------------------------
    # `pending_tasks`/`task_results` have no reducer -- every write is a
    # plain overwrite, which is correct ONLY because delegation is strictly
    # sequential today (one worker runs, reports, control returns to
    # `supervisor`). The first fan-out that runs workers in parallel (the
    # `Send` API, or a genuinely concurrent Phase 8/9 subgraph) would have
    # two branches read-modify-write these fields against the same base
    # state and silently drop one branch's result. Add an `operator.add`
    # (or similar merge) reducer before any node is invoked more than once
    # per super-step.
    supervisor_iterations: int
    pending_tasks: list[str]  # worker node names still owed a turn this cycle
    next_worker: str | None
    task_description: str
    task_results: list[dict[str, Any]]
    routing_source: str  # "impact_map" | "supervisor" | "impact_map_fallback" | "max_iterations" | "day_loop_continuation"
    routing_reasoning: str
    # Bounds the day-rebuild loop's own re-queue hops, SEPARATELY from
    # `supervisor_iterations` (review finding F3): the day loop routes back
    # through `supervisor` once per day by design, and sharing one 5-call
    # budget with the general "prevent infinite delegation" guard silently
    # truncated any itinerary past ~5 days. `load_context` resets this to 0
    # every turn, same as `supervisor_iterations`.
    day_rebuild_hops: int

    # --- itinerary day-rebuild queue (Phase 9) ----------------------------
    # `rebuild_day_queue` holds day numbers still waiting to be processed by
    # `itinerary_node`.  The node pops one day per invocation and returns
    # the shorter queue; the parent graph's conditional edge re-routes back
    # to `itinerary_node` while the queue is non-empty.  This is how the
    # plan's "loop as conditional edge, not Python for" requirement is met:
    # each invocation of `itinerary_node` internally calls the `rebuild_day`
    # subgraph once, getting an independent checkpoint per day.
    rebuild_day_queue: list[int]
    # Days already rebuilt this turn — used by tests to assert byte-identity
    # of other days and to record the audit trail.
    rebuilt_days: list[int]
    # Operations from the edit planner that require suggesting choices to the user
    pending_suggest_operations: list[dict[str, Any]]
    # One "Ngày N: ..." line per day rebuilt so far this rebuild op, built
    # from a before/after activity-name diff (`_describe_day_change`) since
    # `rebuild_days` regenerates a day wholesale rather than emitting
    # `edit_item`-style per-operation adjustments. Accumulates across the
    # day-loop's re-queue hops the same way `rebuilt_days` does; `itinerary_node`
    # resets it to `[]` once the final day's reply is built.
    rebuild_day_summaries: list[str]

    # --- built trip bundle (Phase 9) --------------------------------------
    # Lives OUTSIDE `travel_state` deliberately (review finding F1):
    # `travel_state` round-trips through `TravelState.from_dict()`/`.to_dict()`
    # every turn (`validate_patch`/`apply_patch`), and that round-trip only
    # preserves `ALLOWED_PATHS` keys. Nesting the generated trip bundle
    # inside `travel_state` silently dropped the whole itinerary after
    # exactly one more turn. `trip_data` is carried forward like `messages`:
    # `load_context` does not reset it, only the node that legitimately
    # replaces it (`itinerary_node`, `hotel_node` on a hotel pick) writes it.
    trip_data: dict[str, Any]

    # Set by `POST /hotels/select` for exactly the turn that picks a hotel.
    # `load_context` deliberately does not reset it (same convention as
    # `missing_slots`) so it survives from the turn's `invoke()` input
    # through to `hotel_node`; `hotel_node` is the sole consumer and clears
    # it on every return path so it can never fire on a later, unrelated
    # turn (review finding F2).
    selected_hotel_id: str | None

    # --- persisted hotel search cards ------------------------------------
    # Unlike `task_results`, these cards deliberately survive `load_context`.
    # A follow-up hotel-preference request uses them to retain the cards the
    # user has already seen, then appends only unseen matching candidates.
    # The context prevents reusing availability-sensitive cards after the
    # destination, stay dates, or party size changes.
    previous_hotel_options: list[dict[str, Any]]
    previous_hotel_search_context: dict[str, Any]

    # --- output -----------------------------------------------------------
    response: dict[str, Any]  # PlannerChatResponse field shape (Phase 5 non-functional freeze)


@dataclass(frozen=True)
class SessionManifest:
    """Compact, non-PII summary of `TravelGraphState` the supervisor LLM
    reads instead of the full state — mirrors the legacy `_state_summary`'s
    "booleans and counts only" rule (`src/agents/supervisor.py`), extended
    with the pending-task queue a delegation decision actually needs."""

    has_trip_data: bool
    pending_tasks: tuple[str, ...]
    completed_workers: tuple[str, ...]
    task_description: str
    last_user_message: str

    def render(self) -> str:
        completed = ", ".join(self.completed_workers) if self.completed_workers else "none"
        pending = ", ".join(self.pending_tasks) if self.pending_tasks else "none"
        return (
            "[Session manifest — booleans and task queue only, no facts]\n"
            f"- has_trip_data: {self.has_trip_data}\n"
            f"- pending_tasks: {pending}\n"
            f"- completed_workers: {completed}\n"
            f"- task_description: {self.task_description or '(none)'}\n"
            f"- last_user_message: {self.last_user_message}\n"
        )


def build_manifest(state: TravelGraphState) -> SessionManifest:
    messages = state.get("messages") or []
    last_user_message = ""
    for message in reversed(messages):
        if getattr(message, "type", None) == "human":
            last_user_message = str(getattr(message, "content", ""))
            break
    task_results = state.get("task_results") or []
    return SessionManifest(
        has_trip_data=bool(state.get("trip_data")),
        pending_tasks=tuple(state.get("pending_tasks") or ()),
        completed_workers=tuple(result.get("worker", "") for result in task_results),
        task_description=str(state.get("task_description") or ""),
        last_user_message=last_user_message,
    )


def initial_graph_state(session_id: str, *, language: str = "vi") -> TravelGraphState:
    """Baseline used only by tests and CLI entry points that invoke the
    graph directly without going through `load_context`'s own per-turn
    reset — `load_context` is what a real turn relies on."""
    return TravelGraphState(
        session_id=session_id,
        language=language,
        messages=[],
        travel_state={},
        patch=[],
        intent="",
        proposed_travel_state={},
        applied_changes=[],
        revised_slots=[],
        rejected_changes=[],
        unresolved_amenities=[],
        ambiguous_amenities=[],
        impacted_workflows=[],
        unresolved_resume_text=None,
        missing_slots=[],
        next_question=None,
        extraction_failed=False,
        patch_reason="",
        asks_nearby_places=False,
        pending_clarify_day=None,
        intake_answer=None,
        jailbreak_blocked=False,
        supervisor_iterations=0,
        day_rebuild_hops=0,
        pending_tasks=[],
        next_worker=None,
        task_description="",
        task_results=[],
        routing_source="",
        routing_reasoning="",
        rebuild_day_queue=[],
        rebuilt_days=[],
        pending_suggest_operations=[],
        rebuild_day_summaries=[],
        trip_data={},
        selected_hotel_id=None,
        response={},
    )

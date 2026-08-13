"""`TravelGraphState` — execution state for the `orchestrator=graph` plane.

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
    intent: str  # extract_patch's classification -- audit trail only, never routes (doc §36)
    proposed_travel_state: dict[str, Any]  # validate_patch's output; apply_patch commits it
    applied_changes: list[dict[str, Any]]
    rejected_changes: list[dict[str, Any]]
    impacted_workflows: list[str]  # Workflow labels from detect_impact()
    # Raw text of a `Command(resume=...)` reply that did NOT resolve the
    # ambiguity `interrupt()` paused on (Phase 7) -- `_run_turn_via_graph`
    # (api/routes.py) re-runs it as a normal fresh turn instead of losing
    # it. None on every turn that wasn't a resume, or that resolved cleanly.
    unresolved_resume_text: str | None

    # --- slot gate (Phase 7) --------------------------------------------
    missing_slots: list[str]
    next_question: str | None

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
    routing_source: str  # "impact_map" | "supervisor" | "impact_map_fallback" | "max_iterations"
    routing_reasoning: str

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
        has_trip_data=bool((state.get("travel_state") or {}).get("destination")),
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
        rejected_changes=[],
        impacted_workflows=[],
        unresolved_resume_text=None,
        missing_slots=[],
        next_question=None,
        jailbreak_blocked=False,
        supervisor_iterations=0,
        pending_tasks=[],
        next_worker=None,
        task_description="",
        task_results=[],
        routing_source="",
        routing_reasoning="",
        response={},
    )

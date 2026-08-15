"""Assembles the `StateGraph`: every node, every edge, for the one control
plane a chat turn runs through. See `plans/260812-0927-…/phase-05-graph-
skeleton.md` for the full topology rationale — this module is its literal
`add_node`/`add_edge` realization plus two deliberate, documented
deviations from that doc's shorthand:

- `scope_guard → refuse | extract_patch` is real: `scope_guard` wires the
  shipped jailbreak guard (`detect_jailbreak`, gated by
  `JAILBREAK_GUARD_MODE`) and routes a block straight to `respond`, mirroring
  the legacy plane. The doc's out-of-scope half of this edge (Phase 2's
  `guardrails/scope.py`) was never actually shipped — see
  `nodes/scope_guard.py`'s docstring — so only the jailbreak branch exists
  today. `validate_patch → apply_patch` stays a plain edge: Phase 7 landed
  `interrupt()` for a genuinely-ambiguous date, but `validate_patch` no
  longer produces that case (day/month order always resolves to the DD-MM
  reading) — `interrupt()` is still real infrastructure, just used
  elsewhere (`nodes/hotel_node.py`), not on this edge. See
  `nodes/validate_patch.py`.
- `ask_slot`'s `"ask"` outcome routes to `respond`, not straight to `END`.
  Every path must build the frozen `PlannerChatResponse` shape (Phase 5's
  own functional requirement), and only `respond` does that — see
  `routing.route_ask_slot`'s docstring.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.graph.nodes.apply_patch import apply_patch
from src.agents.graph.nodes.ask_slot import ask_slot
from src.agents.graph.contracts import enforce_contract
from src.agents.graph.nodes.booking_node import booking_node
from src.agents.graph.nodes.budget_check import budget_check
from src.agents.graph.nodes.extract_patch import extract_patch
from src.agents.graph.nodes.hotel_node import hotel_node
from src.agents.graph.nodes.itinerary_node import itinerary_node
from src.agents.graph.nodes.load_context import load_context
from src.agents.graph.nodes.qa_node import build_qa_subgraph
from src.agents.graph.nodes.respond import respond
from src.agents.graph.nodes.scope_guard import scope_guard
from src.agents.graph.nodes.supervisor import supervisor
from src.agents.graph.nodes.validate_patch import validate_patch
from src.agents.graph.routing import all_tasks_done, route_ask_slot, route_scope_guard, route_supervisor
from src.agents.graph.state import TravelGraphState

# Every node this graph wires, by name — used by the topology test to
# assert nothing is orphaned and everything Phase 5 promised actually
# exists.
NODE_NAMES: tuple[str, ...] = (
    "load_context",
    "scope_guard",
    "extract_patch",
    "validate_patch",
    "apply_patch",
    "ask_slot",
    "supervisor",
    "hotel_node",
    "itinerary_node",
    "booking_node",
    "qa_node",
    "budget_check",
    "respond",
)


def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Build and compile `graph_v2`. `checkpointer` is normally the app-
    lifespan Postgres singleton (Phase 4), threaded down the same way
    `build_trip_agent` receives it for the legacy plane; a fresh
    `MemorySaver` is the fallback for CLI/test entry points that have none
    to pass — matching that same function's existing behavior.
    """
    effective_checkpointer = checkpointer if checkpointer is not None else MemorySaver()

    builder = StateGraph(TravelGraphState)

    builder.add_node("load_context", load_context)
    builder.add_node("scope_guard", scope_guard)
    builder.add_node("extract_patch", extract_patch)
    builder.add_node("validate_patch", validate_patch)
    builder.add_node("apply_patch", apply_patch)
    builder.add_node("ask_slot", ask_slot)

    builder.add_node("supervisor", supervisor)
    # CONTRACTS-declared workers are wrapped so a write outside their
    # declared `travel_state` paths raises instead of silently corrupting
    # state another worker owns (doc §36) -- `qa_node` needs no wrapper,
    # its subgraph schema structurally cannot reach `travel_state` at all
    # (see nodes/qa_node.py's docstring).
    builder.add_node("hotel_node", enforce_contract("hotel_node", hotel_node))
    builder.add_node("itinerary_node", enforce_contract("itinerary_node", itinerary_node))
    builder.add_node("booking_node", enforce_contract("booking_node", booking_node))
    builder.add_node("qa_node", build_qa_subgraph(effective_checkpointer))
    builder.add_node("budget_check", budget_check)
    builder.add_node("respond", respond)

    # --- Pipeline: START -> ... -> supervisor ---------------------------
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "scope_guard")
    builder.add_conditional_edges("scope_guard", route_scope_guard, {"blocked": "respond", "proceed": "extract_patch"})
    builder.add_edge("extract_patch", "validate_patch")
    builder.add_edge("validate_patch", "apply_patch")
    builder.add_edge("apply_patch", "ask_slot")
    builder.add_conditional_edges("ask_slot", route_ask_slot, {"ask": "respond", "supervisor": "supervisor"})

    # --- Supervisor -> worker delegation ---------------------------------
    builder.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {
            "hotel_node": "hotel_node",
            "itinerary_node": "itinerary_node",
            "booking_node": "booking_node",
            "qa_node": "qa_node",
            "respond": "respond",  # all tasks done
        },
    )

    # --- Workers -> deterministic completion check -> supervisor or onward
    builder.add_conditional_edges("hotel_node", all_tasks_done, {True: "budget_check", False: "supervisor"})
    builder.add_conditional_edges("itinerary_node", all_tasks_done, {True: "budget_check", False: "supervisor"})
    builder.add_conditional_edges("booking_node", all_tasks_done, {True: "budget_check", False: "supervisor"})
    builder.add_edge("qa_node", "respond")  # read-only: no budget or orchestration follow-up

    builder.add_edge("budget_check", "respond")
    builder.add_edge("respond", END)

    return builder.compile(checkpointer=effective_checkpointer)

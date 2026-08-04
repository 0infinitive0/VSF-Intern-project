"""Agent graph construction.

`build_trip_agent(session)` compiles the trip planner's supervisor ReAct
agent, bound to the four module-level, `ToolRuntime`/`Command`-based tools
(Phase 4, 260802-1437-langgraph-full-orchestration-and-durable-state). It
also builds a `SessionTools` bundle of adapters — see `_ToolAdapter` below
for why that bundle still exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from src.agents.prompts import SUPERVISOR_PROMPT, SUPERVISOR_PROMPT_EN
from src.agents.state import TripState
from src.agents.tools.direct_invoke import invoke_tool_directly
from src.agents.tools.finalize_itinerary import finalize_trip_plan
from src.agents.tools.modify_itinerary import modify_trip_plan
from src.agents.tools.recommend_hotels import recommend_hotels
from src.services.llm import get_reasoning_llm as get_llm

if TYPE_CHECKING:
    from src.agents.session import TripSession

_AGENT_TOOLS = [recommend_hotels, modify_trip_plan, finalize_trip_plan]


class _ToolAdapter:
    """Preserves the pre-Phase-4 `.invoke(args) -> str` calling convention
    that `process_chat_turn`'s deterministic cascade (`_run_select_hotel`,
    `_run_finalize`, `_run_intake`) and every existing test's
    `session.tools.X = _FakeTool(...)` stubbing pattern depend on, while the
    underlying tool is now a module-level `ToolRuntime`/`Command` function
    with no `TripSession` reference at all.

    Bound to one session only to read `session.state`/`session.session_id`
    and write the tool's `Command` update back onto `session.state` — it
    holds no other session-specific behavior. A `ToolRuntime`-typed tool
    cannot be invoked with a bare `.invoke(args)` call (verified empirically:
    it raises a pydantic `ValidationError` for the missing `runtime` field),
    so this drives the tool through `invoke_tool_directly`'s single-node
    graph instead."""

    def __init__(self, tool: Any, session: TripSession) -> None:
        self._tool = tool
        self._session = session

    def invoke(self, args: dict[str, Any]) -> str:
        reply, updates = invoke_tool_directly(
            self._tool, self._session.state, session_id=self._session.session_id, **args
        )
        self._session.state.update(updates)
        return reply


class SessionTools(NamedTuple):
    """The four agent-visible tools, adapted to one session.
    `generate_full_itinerary` is deliberately absent — it is never
    registered with `create_react_agent`, but that registration list is no
    longer the hotel-pick gate's mechanism (tools stopped being a closed
    per-session set in this phase). Each tool now asserts its own
    `pending_hotel_selection` precondition instead — see select_hotel.py's
    module docstring."""

    recommend_hotels: object
    modify_trip_plan: object
    finalize_trip_plan: object


def build_trip_agent(session: TripSession, *, temperature: float = 0.3):
    """Build the trip planner's supervisor ReAct agent, bound to the four
    module-level tools, plus a SessionTools bundle of adapters for the
    deterministic cascade and existing tests. Returns
    (compiled_agent, SessionTools) — the caller stores both on the
    TripSession."""
    tools = SessionTools(
        recommend_hotels=_ToolAdapter(recommend_hotels, session),
        modify_trip_plan=_ToolAdapter(modify_trip_plan, session),
        finalize_trip_plan=_ToolAdapter(finalize_trip_plan, session),
    )
    llm = get_llm(temperature=temperature)
    memory = MemorySaver()
    compiled_agent = create_react_agent(
        llm,
        _AGENT_TOOLS,
        state_schema=TripState,
        checkpointer=memory,
        prompt=SUPERVISOR_PROMPT_EN if session.language == "en" else SUPERVISOR_PROMPT,
    )
    return compiled_agent, tools

"""Agent graph construction.

`build_trip_agent(session)` compiles the trip planner's supervisor ReAct agent,
bound to one session's tool closures. `agent` below is the separate template
graph `POST /api/v1/chat` still serves — unrelated to trip planning, kept alive
here (not in its own deleted example_node.py/example_tool.py scaffolding) only
because that endpoint must keep responding; a full API rewrite is Phase 3's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_react_agent

from src.agents.prompts import SUPERVISOR_PROMPT
from src.agents.state import AgentState
from src.agents.tools.finalize_itinerary import build_finalize_trip_plan_tool
from src.agents.tools.modify_itinerary import build_modify_trip_plan_tool
from src.agents.tools.recommend_hotels import build_recommend_hotels_tool
from src.agents.tools.select_hotel import build_select_hotel_tool
from src.services.llm import get_llm

if TYPE_CHECKING:
    from src.agents.session import TripSession


class SessionTools(NamedTuple):
    """The four agent-visible tools, bound to one session. generate_full_itinerary
    is deliberately absent — it is never registered with create_react_agent, so
    the LLM cannot bypass the hotel-pick gate that select_hotel enforces."""

    recommend_hotels: object
    select_hotel: object
    modify_trip_plan: object
    finalize_trip_plan: object


def build_trip_agent(session: TripSession, *, temperature: float = 0.3):
    """Build the trip planner's supervisor ReAct agent and its session-bound tool
    closures. Returns (compiled_agent, SessionTools) — the caller stores both on
    the TripSession."""
    tools = SessionTools(
        recommend_hotels=build_recommend_hotels_tool(session),
        select_hotel=build_select_hotel_tool(session),
        modify_trip_plan=build_modify_trip_plan_tool(session),
        finalize_trip_plan=build_finalize_trip_plan_tool(session),
    )
    llm = get_llm(temperature=temperature)
    memory = MemorySaver()
    compiled_agent = create_react_agent(
        llm,
        list(tools),
        checkpointer=memory,
        prompt=SUPERVISOR_PROMPT,
    )
    return compiled_agent, tools


async def _analyze_node(state: AgentState) -> dict:
    """Phân tích query từ user."""
    query = state.get("query", "")
    analysis = f"Phân tích: {query}"
    return {"analysis": analysis}


async def _respond_node(state: AgentState) -> dict:
    """Tạo response từ analysis."""
    analysis = state.get("analysis", "")
    error = state.get("error")

    if error:
        return {"response": f"Lỗi: {error}"}

    response = f"Kết quả dựa trên phân tích: {analysis}"
    return {"response": response}


def _should_continue(state: AgentState) -> str:
    """Route based on whether an error occurred during analysis."""
    if state.get("error"):
        return END
    return "respond"


def _build_template_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("analyze", _analyze_node)
    graph.add_node("respond", _respond_node)

    graph.set_entry_point("analyze")
    graph.add_conditional_edges("analyze", _should_continue)
    graph.add_edge("respond", END)

    return graph.compile()


agent = _build_template_graph()

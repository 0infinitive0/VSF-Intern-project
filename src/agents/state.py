from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class TripAgentState(TypedDict):
    """LangGraph message-passing state for the trip planner's supervisor agent.

    `create_react_agent` manages this state internally (tool calls, tool
    results, and the running message history); this schema documents its
    shape for anything that inspects agent state directly.
    """

    messages: Annotated[list, add_messages]

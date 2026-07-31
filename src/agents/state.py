from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """State schema for the template graph POST /api/v1/chat still serves.

    Mỗi node đọc và ghi vào state này.
    total=False cho phép tất cả fields là optional.
    """

    query: str
    context: str
    analysis: str
    response: str
    error: str
    metadata: dict


class TripAgentState(TypedDict):
    """LangGraph message-passing state for the trip planner's supervisor agent.

    `create_react_agent` manages this state internally (tool calls, tool
    results, and the running message history); this schema documents its
    shape for anything that inspects agent state directly.
    """

    messages: Annotated[list, add_messages]

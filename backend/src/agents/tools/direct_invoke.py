"""Adapter for invoking a `ToolRuntime`-based tool directly, outside the LLM
agent's own tool-calling loop.

Phase 4 of 260802-1437-langgraph-full-orchestration-and-durable-state
converts recommend_hotels/select_hotel/finalize_trip_plan from session-bound
closures to module-level `ToolRuntime`/`Command`-based tools. But
`process_chat_turn`'s deterministic cascade calls three of those tools
directly (`select_hotel.invoke({...})`), never through a compiled graph —
and a `ToolRuntime`-typed tool cannot be invoked that way: `runtime` becomes
a required field with no injection source, raising a pydantic
`ValidationError`. Verified empirically, not assumed.

This builds one minimal single-node `StateGraph` per tool (cached — compiling
a graph has real overhead) and drives it with a synthetic `AIMessage`
carrying exactly one tool call, the same mechanism LangGraph's own docs use
to unit-test a `ToolNode` in isolation.
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from src.services.llm import response_text
from src.agents.state import TripState

_compiled_graphs: dict[str, Any] = {}


def _compiled_graph_for(tool: BaseTool) -> Any:
    graph = _compiled_graphs.get(tool.name)
    if graph is None:
        builder = StateGraph(TripState)
        builder.add_node("tools", ToolNode([tool]))
        builder.add_edge(START, "tools")
        builder.add_edge("tools", END)
        graph = builder.compile()
        _compiled_graphs[tool.name] = graph
    return graph


def invoke_tool_directly(
    tool: BaseTool, state: TripState, *, session_id: str, **kwargs: Any
) -> tuple[str, dict[str, Any]]:
    """Run `tool` once against `state` as if the LLM had called it with
    `kwargs`, outside any live agent loop.

    Returns `(reply_text, updates)`: `updates` is the graph's full
    post-execution state (input plus whatever the tool's `Command` changed),
    minus `messages` — ready to be merged onto a `TripSession`'s state with
    `session.state.update(updates)`.
    """
    call_id = str(uuid.uuid4())
    ai_message = AIMessage(content="", tool_calls=[{"name": tool.name, "args": kwargs, "id": call_id}])
    graph = _compiled_graph_for(tool)
    result = graph.invoke(
        {**state, "messages": [ai_message]},
        config={"configurable": {"thread_id": session_id}},
    )
    tool_message = result["messages"][-1]
    updates = {key: value for key, value in result.items() if key != "messages"}
    return response_text(tool_message), updates

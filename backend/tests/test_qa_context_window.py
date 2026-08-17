"""`qa_node.fit_context_window` — the token budget on the only prompt in the
graph that grows with the conversation.

The budget is deliberately measured in tokens, not turns: this transcript
mixes one-word replies with tool payloads carrying whole hotel lists, so a
turn count says nothing about what is actually sent. These tests drive the
budget down to a few hundred tokens rather than building a 30k-token
fixture — the boundary logic is what matters, and it is identical at any
size.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import src.agents.graph.nodes.qa_node as qa_node_module
from src.agents.graph.nodes.qa_node import fit_context_window


@pytest.fixture(autouse=True)
def _small_budget(monkeypatch):
    """A budget small enough that the fixtures below overflow it."""
    settings = qa_node_module.get_settings()
    monkeypatch.setattr(
        qa_node_module,
        "get_settings",
        lambda: type("_S", (), {**settings.model_dump(), "qa_context_token_budget": 120})(),
    )


def _exchange(index: int, *, payload: str = "ngắn") -> list[Any]:
    """One full ReAct exchange: question -> tool call -> tool result -> answer."""
    call_id = f"call_{index}"
    return [
        HumanMessage(content=f"Khách sạn {index} còn phòng không?"),
        AIMessage(
            content="",
            tool_calls=[{"name": "query_hotel_rooms", "args": {"hotel_id": index}, "id": call_id}],
        ),
        ToolMessage(content=payload, tool_call_id=call_id),
        AIMessage(content=f"Khách sạn {index} còn phòng."),
    ]


def _transcript(count: int, *, payload: str = "ngắn") -> list[Any]:
    """`count` finished exchanges plus the question this hop is about to
    answer — the shape the hook really receives. It runs either right after a
    new user message or right after a tool returned, never with a finished
    assistant answer last, which is why `end_on` costs nothing in practice."""
    history = [message for index in range(count) for message in _exchange(index, payload=payload)]
    return [*history, HumanMessage(content="Còn khách sạn nào gần biển không?")]


def test_the_hook_feeds_the_model_without_touching_the_stored_transcript():
    """`llm_input_messages` is what `call_model` reads; `messages` is what the
    conversation keeps. Writing the trimmed list back to `messages` would
    delete history the parent graph still relies on."""
    result = fit_context_window({"messages": _transcript(20)})

    assert set(result) == {"llm_input_messages"}


def test_a_long_transcript_is_cut_down_to_its_newest_slice():
    messages = _transcript(20)

    kept = fit_context_window({"messages": messages})["llm_input_messages"]

    assert len(kept) < len(messages)
    assert kept[-1] is messages[-1]  # newest survives, oldest is what goes


def test_a_short_transcript_passes_through_untouched():
    messages = _transcript(1)

    assert fit_context_window({"messages": messages})["llm_input_messages"] == messages


def test_the_window_never_cuts_a_tool_call_away_from_its_result():
    """An `AIMessage(tool_calls=...)` whose `ToolMessage` was trimmed off — or
    a `ToolMessage` whose call was — is rejected by the provider outright, so
    this is a hard failure the boundary rules exist to prevent, not a quality
    trade-off. A single oversized payload makes the cut land mid-exchange if
    the boundaries are not enforced."""
    messages = _transcript(12, payload="phòng " * 200)

    kept = fit_context_window({"messages": messages})["llm_input_messages"]

    open_call_ids: set[str] = set()
    for message in kept:
        for call in getattr(message, "tool_calls", None) or []:
            open_call_ids.add(call["id"])
        if isinstance(message, ToolMessage):
            assert message.tool_call_id in open_call_ids, "tool result with no call in the window"
            open_call_ids.discard(message.tool_call_id)
    assert not open_call_ids, f"tool calls left unanswered in the window: {open_call_ids}"


def test_the_window_starts_on_a_human_turn():
    kept = fit_context_window({"messages": _transcript(20)})["llm_input_messages"]

    assert isinstance(kept[0], HumanMessage)

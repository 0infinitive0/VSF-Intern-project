"""`session_store.deserialize` — the rehydration path every session takes on
its first turn after a restart (`agents/session.py::resolve`).

Both checkpoint layouts must come back with the same workflow fields: v2
stores them under `workflow`, v1 (rows written before the schema bump, still
readable until their next save) stores them flat at the top level.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, messages_to_dict

from src.services.session_store import _CONTEXT_SCHEMA_VERSION, deserialize


def _workflow_fields() -> dict:
    return {
        "intake": {"destination": "Đà Nẵng", "people": 2},
        "language": "vi",
        "initial_plan_complete": True,
        "pending_hotel_selection": {"mode": "search", "destination": "Đà Nẵng"},
    }


def test_v1_context_restores_the_workflow_fields_not_just_messages():
    """Regression: the v1 branch iterated the empty dict it had just created,
    so every field but `messages` was silently dropped — a session written
    before the schema bump came back as a blank slate mid-conversation."""
    fields = _workflow_fields()
    context = {**fields, "messages": messages_to_dict([HumanMessage(content="chào")])}

    state = deserialize("s1", context)

    for key, value in fields.items():
        assert state.get(key) == value, f"v1 checkpoint dropped {key!r}"
    assert [m.content for m in state["messages"]] == ["chào"]


def test_v1_context_ignores_keys_outside_the_checkpoint_fields():
    """Runtime scratch stored by an old writer must not be resurrected as
    workflow state — the v2 branch restores `_CHECKPOINT_FIELDS` only, and v1
    reads the same list."""
    state = deserialize("s1", {"intake": {"destination": "Huế"}, "remaining_steps": 7, "messages": []})

    assert state["intake"] == {"destination": "Huế"}
    assert "remaining_steps" not in state


def test_v2_context_restores_from_the_workflow_block():
    fields = _workflow_fields()
    context = {"schema_version": _CONTEXT_SCHEMA_VERSION, "workflow": fields}

    state = deserialize("s1", context)

    for key, value in fields.items():
        assert state.get(key) == value


def test_message_rows_win_over_the_checkpoint_transcript():
    """v2 stopped storing the transcript in `context_data`; when the caller
    supplies the `messages` table rows, those are the transcript."""
    context = {**_workflow_fields(), "messages": messages_to_dict([HumanMessage(content="cũ")])}

    state = deserialize("s1", context, [{"sender_type": "user", "message_content": "mới"}])

    assert [m.content for m in state["messages"]] == ["mới"]

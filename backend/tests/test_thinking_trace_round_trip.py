"""The thinking block has to survive a reload.

Two stores, one path: the trace is stamped onto the reply's message, written to
`chat_messages.thinking_trace` with that row, and read back out when the
conversation is restored. Each leg is checked here, plus the leg that matters
most in practice — a message that has no trace at all, which is every row
written before the column existed.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from src.services.session_store import _graph_message_records, restored_messages

_TRACE = [
    {"phase_key": "intake_check", "facts": {"intent": "general_question"}},
    {"phase_key": "generating", "facts": {}},
]


def _reply(text: str, *, trace=None) -> AIMessage:
    """An assistant turn as `respond` writes it — the tag is what marks a reply."""
    metadata = {"emitted_by": "respond", "at": "2026-08-19T00:00:00Z"}
    if trace is not None:
        metadata["thinking_trace"] = trace
    return AIMessage(content=text, additional_kwargs=metadata)


class TestWritingTheTrace:
    def test_the_reply_row_carries_the_turn_that_produced_it(self):
        records = _graph_message_records(
            {"messages": [HumanMessage(content="xin chào"), _reply("Chào bạn!", trace=_TRACE)]}
        )

        assert records[-1]["thinking_trace"] == _TRACE

    def test_a_reply_without_a_trace_writes_null_rather_than_failing(self):
        records = _graph_message_records({"messages": [_reply("Chào bạn!")]})

        assert records[-1]["thinking_trace"] is None

    def test_facts_are_stored_not_sentences(self):
        """Sentences depend on the reader's language and on today's wording;
        storing them would render a Vietnamese turn in Vietnamese inside an
        English session, and freeze the phrasing into history."""
        records = _graph_message_records({"messages": [_reply("Chào bạn!", trace=_TRACE)]})

        stored = str(records[-1]["thinking_trace"])
        assert "intake_check" in stored
        assert "Nhận diện" not in stored


class TestReadingItBack:
    def test_a_stored_trace_reaches_the_restore_payload(self):
        rows = [
            {
                "sender_type": "assistant",
                "message_content": "Chào bạn!",
                "created_at": "2026-08-19T00:00:00Z",
                "thinking_trace": _TRACE,
            }
        ]

        assert restored_messages(rows)[0]["thinking_trace"] == _TRACE

    def test_a_row_written_before_the_column_existed_restores_cleanly(self):
        """The ordinary case, not an edge one: every message already in the
        database predates this column."""
        rows = [
            {
                "sender_type": "assistant",
                "message_content": "Chào bạn!",
                "created_at": "2026-08-19T00:00:00Z",
            }
        ]

        restored = restored_messages(rows)

        assert restored[0]["thinking_trace"] is None
        assert restored[0]["text"] == "Chào bạn!"


class TestTheFullTrip:
    def test_what_is_written_is_what_comes_back(self):
        records = _graph_message_records(
            {"messages": [HumanMessage(content="xin chào"), _reply("Chào bạn!", trace=_TRACE)]}
        )
        # `load()` hands the rows straight through; this is that shape.
        restored = restored_messages(records)

        assert restored[-1]["thinking_trace"] == _TRACE
        assert restored[-1]["text"] == "Chào bạn!"


class TestTheTraceIsCollectedFromARealTurn:
    """The leg the unit tests above cannot reach: the drain records each step as
    it completes, and the turn hands them to the persist call.

    The trace deliberately does NOT travel on the message. `app.get_state()`
    returns a fresh copy on every call, so a trace stamped onto a message there
    is gone before `_persist_turn` reads the state back — which is exactly the
    bug this test caught.
    """

    def test_a_streamed_turn_persists_the_steps_it_ran(self, monkeypatch):
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

        import src.agents.graph.graph as graph_module
        import src.agents.graph.nodes.intake_qa as intake_qa_module
        import src.api.routes as routes
        from src.api.streaming import emitting_to
        from src.domain.travel_state import TravelState, apply_patch

        class _Fake(GenericFakeChatModel):
            def bind_tools(self, *_a, **_k):
                return self

        monkeypatch.setattr(
            intake_qa_module,
            "get_fast_llm",
            lambda **_k: _Fake(messages=iter([AIMessage(content="Tháng 7 hay mưa.")] * 9)),
        )
        monkeypatch.setattr(
            graph_module, "extract_patch", lambda _s: {"patch": [], "intent": "general_question"}
        )
        app = graph_module.build_graph()
        monkeypatch.setattr(routes, "_get_graph_v2", lambda: app)
        monkeypatch.setattr(routes, "_persistence_enabled", True)

        captured: dict[str, Any] = {}

        def _capture(session, state, thinking_trace=None):
            captured["records"] = _graph_message_records(state, thinking_trace)

        monkeypatch.setattr(routes.session_store, "persist_graph_session", _capture)
        monkeypatch.setattr(routes.registry, "get", lambda _sid: object())

        travel_state = apply_patch(
            TravelState(),
            [
                {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
                {"path": "people", "operation": "set", "value": 2},
            ],
        ).state.to_dict()

        class _Silent:
            def emit(self, *_a, **_k):
                pass

        with emitting_to(_Silent()):  # type: ignore[arg-type]
            routes._run_turn_via_graph(
                "trace-round-trip",
                "Đà Nẵng tháng 7 thời tiết thế nào?",
                "vi",
                extra_state={"travel_state": travel_state},
                stream=True,
            )

        records = captured.get("records")
        assert records, "nothing was persisted, so there is nothing to restore"

        replies = [r for r in records if r["sender_type"] == "assistant"]
        trace = replies[-1]["thinking_trace"]
        assert trace, "the reply row carries no trace, so a reload would show nothing"
        assert any(entry["phase_key"] == "intake_check" for entry in trace)
        # Facts ride the completed edge, so the classification is in there.
        assert any(entry["facts"] for entry in trace)


class TestTheReadSelectsWhatTheWriteStores:
    """A column added to the write path is invisible until the read names it too.

    `load()` selects an explicit column list. `thinking_trace` was written
    correctly, stored correctly, and still came back `None` on every restore
    for exactly this reason — the select had not been updated, and nothing
    failed to say so.
    """

    def test_every_stored_column_is_selected_back(self):
        import inspect

        from src.services import session_store

        written = set(
            _graph_message_records(
                {"messages": [_reply("Chào bạn!", trace=_TRACE)]}, _TRACE
            )[0]
        )
        # The column list lives in the query, so read it from there.
        source = inspect.getsource(session_store)
        select_line = next(
            line for line in source.splitlines() if ".select(" in line and "message_content" in line
        )
        selected = set(select_line.split('"')[1].split(","))

        missing = written - selected
        assert not missing, f"written but never read back: {sorted(missing)}"

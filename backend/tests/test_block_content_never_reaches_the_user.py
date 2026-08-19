"""A block-shaped answer must never reach the user as a Python repr.

Reported from a real session: the user typed "xin chào" and got back the raw
Responses API content list — reasoning block, `encrypted_content` and all —
rendered as its `str()`. Four call sites read `.content` this way; each is
covered here, because the shape reaches them by four different routes.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.graph.nodes.respond import _reply_from_messages  # type: ignore[attr-defined]

#: Exactly what the Responses API sends for a short greeting.
_GREETING_BLOCKS = [
    {
        "id": "rs_0574a02d",
        "summary": [{"index": 0, "type": "summary_text", "text": "**Responding in Vietnamese**"}],
        "type": "reasoning",
        "encrypted_content": "gAAAAABqhVHFBc56lPZtMfZ",
    },
    {"type": "text", "text": "Xin chào! Bạn cần mình giúp gì hôm nay?", "index": 1},
]


def _state(messages):
    return {"messages": messages}


class TestTheReplyTheUserSees:
    def test_a_block_shaped_answer_becomes_its_text(self):
        answer = _reply_from_messages(
            _state([HumanMessage(content="xin chào"), AIMessage(content=_GREETING_BLOCKS)])
        )

        assert answer == "Xin chào! Bạn cần mình giúp gì hôm nay?"

    def test_the_encrypted_reasoning_payload_never_reaches_the_user(self):
        answer = _reply_from_messages(
            _state([HumanMessage(content="xin chào"), AIMessage(content=_GREETING_BLOCKS)])
        ) or ""

        assert "encrypted_content" not in answer
        assert "gAAAAAB" not in answer
        assert "summary_text" not in answer

    def test_a_plain_string_answer_is_unchanged(self):
        answer = _reply_from_messages(
            _state([HumanMessage(content="xin chào"), AIMessage(content="Xin chào!")])
        )

        assert answer == "Xin chào!"

    def test_an_answer_with_only_reasoning_is_no_answer(self):
        """Better to fall through to the next reply source than to show the
        user the model thinking about a reply it never wrote."""
        answer = _reply_from_messages(
            _state([HumanMessage(content="xin chào"), AIMessage(content=_GREETING_BLOCKS[:1])])
        )

        assert answer is None


class TestWhatGetsWrittenToTheDatabase:
    def test_a_block_shaped_message_is_stored_as_its_text(self):
        from src.services.session_store import _message_records

        class _Session:
            state = {"messages": [AIMessage(content=_GREETING_BLOCKS)]}

        records = _message_records(_Session())  # type: ignore[arg-type]

        assert records[0]["message_content"] == "Xin chào! Bạn cần mình giúp gì hôm nay?"
        assert "encrypted_content" not in records[0]["message_content"]

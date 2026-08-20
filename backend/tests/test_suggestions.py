"""`generate_next_chat_suggestions` -- always an LLM call, always grounded in
the `SuggestionContext` passed in, never a hardcoded list.

No test here calls a real model: `get_fast_llm` is monkeypatched on the
suggestions module in every case, same pattern as
`test_supervisor_routing.py`'s `_FakeLLM`/`_FakeStructuredLLM`.
"""

from __future__ import annotations

import dataclasses
import logging

import src.services.suggestions as suggestions_module
from src.services.suggestions import (
    NextChatSuggestions,
    SuggestionContext,
    SuggestionHotelCard,
    generate_next_chat_suggestions,
)


class _FakeStructuredLLM:
    def __init__(self, result: NextChatSuggestions | None, exc: Exception | None):
        self._result = result
        self._exc = exc

    def invoke(self, _messages):
        if self._exc is not None:
            raise self._exc
        return self._result


class _FakeLLM:
    def __init__(self, result: NextChatSuggestions | None = None, exc: Exception | None = None):
        self._result = result
        self._exc = exc

    def with_structured_output(self, _model):
        return _FakeStructuredLLM(self._result, self._exc)


def _patch(monkeypatch, *, result: NextChatSuggestions | None = None, exc: Exception | None = None):
    captured: dict = {}

    def _fake_get_llm(**kwargs):
        captured["kwargs"] = kwargs
        return _FakeLLM(result, exc)

    monkeypatch.setattr(suggestions_module, "get_llm", _fake_get_llm)
    return captured


_BASE_CONTEXT = SuggestionContext(
    worker="hotel_node",
    status="ok",
    reply="Đây là 3 khách sạn phù hợp.",
    language="vi",
    destination="Đà Nẵng",
    hotel_cards=(
        SuggestionHotelCard(name="Khách sạn A", price=800000, review_score=8.5),
        SuggestionHotelCard(name="Khách sạn B", price=1200000, review_score=9.1),
    ),
    hotel_amenity_labels=("Hồ bơi", "Bữa sáng miễn phí"),
    active_filter_labels=(),
    trip_duration_days=None,
)


def _context(**overrides) -> SuggestionContext:
    return dataclasses.replace(_BASE_CONTEXT, **overrides)


_PROMPTS = ["Lọc khách sạn có điểm đánh giá trên 9", "Tìm khách sạn có hồ bơi", "Xem chi tiết Khách sạn B"]


def test_a_normal_result_is_returned(monkeypatch):
    captured = _patch(monkeypatch, result=NextChatSuggestions(suggestions=_PROMPTS))

    assert generate_next_chat_suggestions(_context()) == _PROMPTS
    # `get_llm`'s own timeout only bounds the OpenAI branch (its docstring);
    # this is still passed on every call so that branch stays covered.
    assert captured["kwargs"]["timeout"] == suggestions_module._DEFAULT_TIMEOUT_SECONDS


def test_a_hanging_call_times_out_and_returns_empty(monkeypatch, caplog):
    """The wall-clock guard (`concurrent.futures`) is what actually bounds a
    provider with no request-level timeout of its own (the local Ollama
    fallback) -- `get_llm`'s `timeout=` kwarg only reaches the OpenAI branch."""
    import threading

    class _HangingStructured:
        def invoke(self, _messages):
            threading.Event().wait(30)  # far longer than the test's own timeout
            raise AssertionError("unreachable")

    class _HangingLLM:
        def with_structured_output(self, _model):
            return _HangingStructured()

    monkeypatch.setattr(suggestions_module, "get_llm", lambda **_kwargs: _HangingLLM())
    monkeypatch.setattr(suggestions_module, "_DEFAULT_TIMEOUT_SECONDS", 0.05)

    with caplog.at_level(logging.WARNING):
        result = generate_next_chat_suggestions(_context())

    assert result == []
    assert any("timed out" in record.message for record in caplog.records)


def test_prompt_states_the_no_fabrication_and_grounded_number_constraints(monkeypatch):
    captured = {}

    class _CapturingStructured:
        def invoke(self, messages):
            captured["prompt"] = messages[0].content
            return NextChatSuggestions(suggestions=_PROMPTS)

    class _CapturingLLM:
        def with_structured_output(self, _model):
            return _CapturingStructured()

    monkeypatch.setattr(suggestions_module, "get_llm", lambda **_kwargs: _CapturingLLM())

    generate_next_chat_suggestions(_context(hotel_amenity_labels=("Hồ bơi",)))

    prompt = captured["prompt"]
    assert "Hồ bơi" in prompt
    assert "không bịa thêm" in prompt
    assert "PHẢI kèm số cụ thể" in prompt


def test_language_en_asks_for_english_output(monkeypatch):
    captured = {}

    class _CapturingStructured:
        def invoke(self, messages):
            captured["prompt"] = messages[0].content
            return NextChatSuggestions(suggestions=["Filter hotels above 9.0 rating"])

    class _CapturingLLM:
        def with_structured_output(self, _model):
            return _CapturingStructured()

    monkeypatch.setattr(suggestions_module, "get_llm", lambda **_kwargs: _CapturingLLM())

    generate_next_chat_suggestions(_context(language="en"))

    assert "tiếng Anh" in captured["prompt"]


def test_llm_exception_returns_empty_list_and_logs_warning(monkeypatch, caplog):
    _patch(monkeypatch, exc=RuntimeError("boom"))

    with caplog.at_level(logging.WARNING):
        result = generate_next_chat_suggestions(_context())

    assert result == []
    assert any("generate_next_chat_suggestions failed" in record.message for record in caplog.records)


def test_llm_returns_empty_list_logs_warning_and_returns_empty(monkeypatch, caplog):
    _patch(monkeypatch, result=NextChatSuggestions(suggestions=[]))

    with caplog.at_level(logging.WARNING):
        result = generate_next_chat_suggestions(_context())

    assert result == []
    assert any("no usable suggestions" in record.message for record in caplog.records)


def test_wrong_shape_from_structured_output_returns_empty_and_logs(monkeypatch, caplog):
    """`with_structured_output` is contractually supposed to return the pydantic
    model, but a defensive check still guards a provider that hands back
    something else (e.g. `None` on a tool-call-less response)."""
    _patch(monkeypatch, result=None)

    with caplog.at_level(logging.WARNING):
        result = generate_next_chat_suggestions(_context())

    assert result == []
    assert any("structured output returned" in record.message for record in caplog.records)


def test_numbered_prefix_is_stripped_and_duplicates_case_insensitive_are_removed(monkeypatch):
    _patch(
        monkeypatch,
        result=NextChatSuggestions(
            suggestions=[
                "1. Lọc khách sạn có hồ bơi",
                "Lọc khách sạn có hồ bơi",  # exact dup
                "LỌC KHÁCH SẠN CÓ HỒ BƠI",  # case-insensitive dup
                "2) Xem chi tiết Khách sạn B",
                "",  # empty, dropped
            ]
        ),
    )

    result = generate_next_chat_suggestions(_context(), limit=5)

    assert result == ["Lọc khách sạn có hồ bơi", "Xem chi tiết Khách sạn B"]


def test_limit_is_respected(monkeypatch):
    _patch(monkeypatch, result=NextChatSuggestions(suggestions=_PROMPTS))

    assert len(generate_next_chat_suggestions(_context(), limit=1)) == 1


def test_no_hardcoded_suggestion_strings_survive_in_the_module_source():
    """Regression guard for the bug this plan fixes: the old module returned
    these exact literals regardless of what the turn actually did."""
    import inspect

    source = inspect.getsource(suggestions_module)
    for banned in ("Lọc theo đánh giá cao hơn", "Khách sạn nào có đánh giá cao nhất?", "Tóm tắt chi phí"):
        assert banned not in source

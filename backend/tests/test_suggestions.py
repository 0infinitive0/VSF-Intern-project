"""`generate_next_chat_suggestions` reads the model's JSON array of prompts.

It used to call `response.content.strip()` — an `AttributeError` on the list the
Responses API returns, swallowed by the function's broad `except`, leaving the
chat with no follow-up suggestions and no sign of why.
"""

from __future__ import annotations

import json

import src.services.suggestions as suggestions_module


class _Response:
    def __init__(self, content) -> None:
        self.content = content


class _FakeLLM:
    def __init__(self, content) -> None:
        self._content = content

    def invoke(self, _messages) -> _Response:
        return _Response(self._content)


def _patch(monkeypatch, content) -> None:
    monkeypatch.setattr(suggestions_module, "get_llm", lambda **_kwargs: _FakeLLM(content))


_PROMPTS = ["Thêm một ngày ở Hội An", "Đổi khách sạn rẻ hơn", "Bỏ bữa tối ngày 2"]


def test_a_plain_string_response_still_works(monkeypatch):
    _patch(monkeypatch, json.dumps(_PROMPTS, ensure_ascii=False))

    assert suggestions_module.generate_next_chat_suggestions("lịch trình 3 ngày") == _PROMPTS


def test_a_block_shaped_response_yields_the_same_suggestions(monkeypatch):
    _patch(monkeypatch, [{"type": "text", "text": json.dumps(_PROMPTS, ensure_ascii=False)}])

    assert suggestions_module.generate_next_chat_suggestions("lịch trình 3 ngày") == _PROMPTS


def test_a_reasoning_only_response_falls_back_without_raising(monkeypatch):
    """No text block means no JSON. The fallback is the contract here — the one
    thing that must not happen is an exception reaching the caller."""
    _patch(monkeypatch, [{"type": "reasoning", "reasoning": "Deciding what to suggest"}])

    result = suggestions_module.generate_next_chat_suggestions("lịch trình 3 ngày")

    assert isinstance(result, list)

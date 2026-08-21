"""`pick_shown_option` — the model picks a POSITION, this module decides
whether to trust it.

Every test here stubs the provider. What is under test is the boundary: an
answer outside the closed list, a malformed answer, and a provider failure
must all become "no pick" rather than a card the user did not choose.
"""

from __future__ import annotations

import pytest

import src.services.shortlist_pick as shortlist_pick_module
from src.services.shortlist_pick import ShortlistPick, pick_shown_option

_OPTIONS = [
    {"id": "h1", "name": "Horizon Hotel Apartment", "star_rating": 2, "average_nightly_price": 975610},
    {"id": "h2", "name": "Khách sạn Hòa Bình", "star_rating": 4, "review_score": 8.6, "area_name": "Hoàn Kiếm"},
]


class _FakeStructured:
    def __init__(self, result, exc=None):
        self._result = result
        self._exc = exc
        self.prompts: list[str] = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        if self._exc is not None:
            raise self._exc
        return self._result


class _FakeLLM:
    def __init__(self, result=None, exc=None):
        self.structured = _FakeStructured(result, exc)

    def with_structured_output(self, _model):
        return self.structured


def _install(monkeypatch, result=None, exc=None) -> _FakeLLM:
    llm = _FakeLLM(result, exc)
    monkeypatch.setattr(shortlist_pick_module, "get_fast_llm", lambda **_kwargs: llm)
    return llm


def _unreachable(*_args, **_kwargs):
    raise AssertionError("no provider call should happen for this input")


def test_a_valid_position_is_returned(monkeypatch):
    _install(monkeypatch, ShortlistPick(position=2, reasoning="named it"))

    assert pick_shown_option("cho mình Hòa Bình", _OPTIONS) == 2


def test_null_position_means_no_pick(monkeypatch):
    _install(monkeypatch, ShortlistPick(position=None, reasoning="a filter, not a pick"))

    assert pick_shown_option("khách sạn 5 sao", _OPTIONS) is None


@pytest.mark.parametrize("position", [0, 3, 12, -1])
def test_a_position_outside_the_shown_list_is_discarded(monkeypatch, position):
    """Not clamped: the nearest card is not a better guess than asking."""
    _install(monkeypatch, ShortlistPick(position=position, reasoning="x"))

    assert pick_shown_option("khách sạn số 12", _OPTIONS) is None


def test_a_malformed_answer_is_discarded(monkeypatch):
    _install(monkeypatch, object())

    assert pick_shown_option("chọn cái đầu", _OPTIONS) is None


def test_a_provider_failure_is_an_unresolved_pick_not_a_raised_turn(monkeypatch):
    _install(monkeypatch, exc=RuntimeError("provider down"))

    assert pick_shown_option("chọn cái đầu", _OPTIONS) is None


def test_no_cards_and_no_message_never_reach_the_provider(monkeypatch):
    monkeypatch.setattr(shortlist_pick_module, "get_fast_llm", _unreachable)

    assert pick_shown_option("chọn cái đầu", []) is None
    assert pick_shown_option("   ", _OPTIONS) is None


def test_the_prompt_numbers_the_cards_in_list_order(monkeypatch):
    """The number the model is shown must be the number the user is shown —
    position in this list, not any `rank` field a card happens to carry."""
    llm = _install(monkeypatch, ShortlistPick(position=1, reasoning="x"))

    pick_shown_option("chọn cái đầu", [{"rank": 9, **_OPTIONS[0]}, _OPTIONS[1]])

    prompt = llm.structured.prompts[0]
    assert "1. Horizon Hotel Apartment" in prompt
    assert "2. Khách sạn Hòa Bình" in prompt


def test_card_lines_carry_the_facts_a_description_can_point_at(monkeypatch):
    """"cái rẻ nhất" / "cái ở Hoàn Kiếm" only resolve if the model sees them."""
    llm = _install(monkeypatch, ShortlistPick(position=1, reasoning="x"))

    pick_shown_option("cái rẻ nhất", _OPTIONS)

    prompt = llm.structured.prompts[0]
    assert "975.610 VND/đêm" in prompt
    assert "4 sao" in prompt
    assert "điểm đánh giá 8.6" in prompt
    assert "Hoàn Kiếm" in prompt


def test_a_long_merged_list_is_capped(monkeypatch):
    llm = _install(monkeypatch, ShortlistPick(position=1, reasoning="x"))
    many = [{"id": f"h{n}", "name": f"Hotel {n}"} for n in range(1, 41)]

    pick_shown_option("chọn cái đầu", many)

    prompt = llm.structured.prompts[0]
    assert "30. Hotel 30" in prompt
    assert "31. Hotel 31" not in prompt

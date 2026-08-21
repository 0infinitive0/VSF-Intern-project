"""`ask_slot`'s question rendering, split by what owns the wording.

Three layers, because they do not have the same author:

- `_render_question` writes the question text. It is a pure `if/elif` over
  `SlotSpec.prompt_key` and stays that way — byte-exact assertions belong
  here and nowhere else. In particular `test_render_question_is_translated`
  pins the English string byte-for-byte against the frontend's own
  `intakeDatesQuestion` (`frontend/src/i18n/locales/en.json`); the two
  surfaces asking different things is the bug this whole slot registry was
  built to end.
- `_context_line` writes the line ABOVE the question — the rejection
  explanation or the "didn't catch that" framing. Its wording is asserted
  here too, on the function itself.
- `ask_slot` (the node) only decides WHICH slots are pending and glues the
  two together. Its tests assert `missing_slots` and the composition, never
  the wording — `missing_slots` is what actually encodes "asking about both
  ends" vs "asking about the end only", and it is what every downstream
  consumer (`extract_patch`'s anchor, `respond`'s `asked_slot` tag) reads.

Keeping wording out of the node's own tests is deliberate: it is the layer
whose text is expected to stop being a fixed string, while `_render_question`
remains as the fallback underneath it.

Every test runs with the rewording model UNAVAILABLE by default
(`_rewording_unavailable`, autouse), so `ask_slot` returns
`_render_question`'s output verbatim — which is both what layer 3 asserts
against and a standing check that the degrade path works. The tests that
exercise the rewording patch `get_fast_llm` themselves.

Only `_destination_catalog`'s own tests reach the destination list, and they
patch `_get_destination_names` — nothing here hits Supabase.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import src.agents.graph.nodes.ask_slot as ask_slot_module
from src.agents.graph.nodes.extract_patch import UNKNOWN_DESTINATION_REASON, UNSUPPORTED_LABEL_REASON
from src.agents.graph.nodes.ask_slot import (
    _context_line,
    _render_preferences,
    _render_question,
    _slot_choices,
    _slot_question_is_usable,
    ask_slot,
)
from src.agents.graph.state import TravelGraphState, initial_graph_state
from src.domain.slot_registry import SLOT_REGISTRY, SlotSpec, next_question, pending_question_slots
from src.domain.travel_state import END_NOT_AFTER_START_REASON, TravelState

_FUTURE_START = (date.today() + timedelta(days=30)).isoformat()
_ANSWERED = {
    "destination": {"presence": "set", "value": "Đà Nẵng"},
    "people": {"presence": "set", "value": 2},
}
_START_ANSWERED = {**_ANSWERED, "dates.start": {"presence": "set", "value": _FUTURE_START}}
_DATES_ANSWERED = {
    **_START_ANSWERED,
    "dates.end": {"presence": "set", "value": (date.today() + timedelta(days=34)).isoformat()},
}


class _FakeLLM:
    """One canned response per `.invoke()`, recording the prompts it saw."""

    def __init__(self, content: str | Exception) -> None:
        self._content = content
        self.prompts: list[str] = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        if isinstance(self._content, Exception):
            raise self._content
        return type("_Response", (), {"content": self._content})()


def _use_rewording(monkeypatch, content: str | Exception) -> _FakeLLM:
    llm = _FakeLLM(content)
    monkeypatch.setattr(ask_slot_module, "get_fast_llm", lambda **_kwargs: llm)
    return llm


def _state(travel_state: dict, *, language: str = "vi") -> TravelGraphState:
    state = initial_graph_state("t1")
    state["language"] = language
    state["travel_state"] = travel_state
    return state


def _pending_for(travel_state: dict) -> tuple[SlotSpec, tuple[str, ...]]:
    """The `(spec, pending)` pair `ask_slot` itself would compute for this
    state — derived the same way, so a layer-1 test can never assert against
    a slot pairing the node would never actually produce."""
    parsed = TravelState.from_dict(travel_state)
    spec = next_question(parsed)
    assert spec is not None, "fixture has no slot left to ask about"
    return spec, pending_question_slots(parsed)


def _spec_for(travel_state: dict) -> SlotSpec:
    """`_pending_for`'s first half, for the layers that render off the spec
    alone and never see the pending tuple (`_context_line`)."""
    return _pending_for(travel_state)[0]


# --- Layer 1: `_render_question` owns the question wording -------------------


def test_render_question_asks_for_both_ends_while_both_dates_are_missing() -> None:
    spec, pending = _pending_for(dict(_ANSWERED))

    assert _render_question(spec, pending, "vi") == "Bạn dự định đi và về ngày nào?"


def test_render_question_narrows_once_the_start_is_known() -> None:
    """One date alone is a legitimate answer: the other slot stays pending
    and the question stops asking for the date already given."""
    spec, pending = _pending_for(dict(_START_ANSWERED))

    question = _render_question(spec, pending, "vi")

    assert question == "Bạn dự định kết thúc chuyến đi vào ngày nào?"
    assert "đi và về" not in question


def test_render_question_is_translated() -> None:
    """Byte-identical to the frontend's own `intakeDatesQuestion` in both
    languages — the whole point is that the two surfaces stop asking
    different things."""
    spec, pending = _pending_for(dict(_ANSWERED))

    assert _render_question(spec, pending, "en") == "When do you plan to depart and return?"


# --- Layer 2: `_context_line` owns the line above the question ---------------


def test_a_same_day_trip_is_explained_not_dumped_as_a_validator_string() -> None:
    """"đi Huế trong 1 ngày" resolves to end == start and is rejected. The reply the
    user saw was the validator's own English sentence — "Dữ liệu chưa hợp lệ: end date
    must be after the trip's start date" — which reads as an internal error and says
    nothing about what to do next."""
    travel_state = dict(_START_ANSWERED)
    state = _state(travel_state)
    state["rejected_changes"] = [
        {"path": "dates.end", "reason": f"dates.end: {END_NOT_AFTER_START_REASON}"}
    ]
    spec = _spec_for(travel_state)

    context = _context_line(state, spec, "vi", TravelState.from_dict(travel_state))

    assert context is not None
    assert END_NOT_AFTER_START_REASON not in context
    assert "ít nhất 1 đêm" in context


def test_an_unrecognised_rejection_still_shows_its_reason() -> None:
    """Only the same-day case is special-cased; anything else must keep surfacing
    the reason rather than silently becoming a bare re-ask."""
    travel_state = dict(_START_ANSWERED)
    state = _state(travel_state)
    state["rejected_changes"] = [{"path": "dates.end", "reason": "dates.end: expected YYYY-MM-DD"}]
    spec = _spec_for(travel_state)

    context = _context_line(state, spec, "vi", TravelState.from_dict(travel_state))

    assert context is not None
    assert "expected YYYY-MM-DD" in context


def test_no_context_line_on_a_slot_s_first_ever_ask() -> None:
    """Nothing to have "not caught" yet — the framing is scoped to a genuine
    re-ask, and this is what keeps a first question from opening with an
    apology."""
    travel_state = dict(_ANSWERED)
    state = _state(travel_state)

    assert _context_line(state, _spec_for(travel_state), "vi", TravelState.from_dict(travel_state)) is None


# --- Layer 3: `ask_slot` owns which slots are pending, not the wording -------


def test_dates_question_covers_both_ends_at_once() -> None:
    result = ask_slot(_state(dict(_ANSWERED)))

    assert result["missing_slots"] == ["dates.start", "dates.end"]


def test_answering_only_the_start_narrows_to_the_end_date_slot() -> None:
    result = ask_slot(_state(dict(_START_ANSWERED)))

    assert result["missing_slots"] == ["dates.end"]


def test_a_rejection_is_prefixed_above_the_question_not_instead_of_it() -> None:
    """Composition only: the explanation goes first, the question still
    follows it, and the two are separated rather than run together. What
    each half says is layer 1's and layer 2's business."""
    travel_state = dict(_START_ANSWERED)
    state = _state(travel_state)
    state["rejected_changes"] = [{"path": "dates.end", "reason": "dates.end: expected YYYY-MM-DD"}]
    context = _context_line(state, _spec_for(travel_state), "vi", TravelState.from_dict(travel_state))
    assert context is not None

    reply = ask_slot(state)["next_question"]

    assert reply.startswith(context)
    assert len(reply) > len(context)


def test_no_rejection_means_the_question_stands_alone() -> None:
    """The counterpart to the test above: without a context line the reply is
    the question and nothing else, so the separator above is a real signal."""
    reply = ask_slot(_state(dict(_ANSWERED)))["next_question"]

    assert "\n\n" not in reply


# --- Layer 1b: the rewording replaces the hardcoded question, or nothing -----


def test_a_usable_rewording_replaces_the_hardcoded_question(monkeypatch) -> None:
    reworded = "Bạn tính khởi hành và quay về vào ngày nào thế?"
    _use_rewording(monkeypatch, reworded)

    assert ask_slot(_state(dict(_ANSWERED)))["next_question"] == reworded


def test_the_rewording_prompt_carries_the_hardcoded_question_as_its_anchor(monkeypatch) -> None:
    """The model is handed the exact sentence it is rewording, which is what
    bounds it to a rephrase instead of a redirect to some other slot."""
    llm = _use_rewording(monkeypatch, "Bạn đi và về ngày nào ạ?")
    spec, pending = _pending_for(dict(_ANSWERED))

    ask_slot(_state(dict(_ANSWERED)))

    assert _render_question(spec, pending, "vi") in llm.prompts[0]


@pytest.mark.parametrize(
    ("rewording", "reason"),
    [
        ("Bạn đi ngày nào?\nVà về ngày nào?", "a line break reads as the context-line separator"),
        ("Cho mình biết ngày đi và ngày về.", "not a question"),
        ("", "empty"),
        ("x" * 400 + "?", "over the length cap"),
    ],
)
def test_an_unusable_rewording_falls_back_to_the_hardcoded_question(
    monkeypatch, rewording: str, reason: str
) -> None:
    _use_rewording(monkeypatch, rewording)
    spec, pending = _pending_for(dict(_ANSWERED))

    result = ask_slot(_state(dict(_ANSWERED)))

    assert result["next_question"] == _render_question(spec, pending, "vi"), reason


def test_a_model_failure_falls_back_to_the_hardcoded_question(monkeypatch) -> None:
    """A provider outage costs the wording, never the turn — the question
    still goes out and the intake still moves."""
    _use_rewording(monkeypatch, RuntimeError("provider down"))
    spec, pending = _pending_for(dict(_ANSWERED))

    result = ask_slot(_state(dict(_ANSWERED)))

    assert result["next_question"] == _render_question(spec, pending, "vi")


def test_a_budget_rewording_that_presents_a_menu_is_discarded(monkeypatch) -> None:
    """Nothing parses menu indices: a bare "2" reply is read by the extractor
    as `people=2`, its only other bare-integer path. See `_render_budget`."""
    _use_rewording(monkeypatch, "Chọn mức giá: 1. dưới 2 triệu 2. từ 2-4 triệu 3. trên 4 triệu?")
    spec, pending = _pending_for(dict(_DATES_ANSWERED))
    assert spec.prompt_key == "budget"

    result = ask_slot(_state(dict(_DATES_ANSWERED)))

    assert result["next_question"] == _render_question(spec, pending, "vi")


def test_a_destination_rewording_that_drops_a_catalog_entry_is_discarded(monkeypatch) -> None:
    """An entry the question omits is an option the user cannot discover, and
    one it invents is an answer `_match_known_destination` will refuse."""
    monkeypatch.setattr(ask_slot_module, "_get_destination_names", lambda: ("Đà Nẵng", "Huế", "Hội An"))
    _use_rewording(monkeypatch, "Bạn muốn đi Đà Nẵng hay Huế?")  # drops Hội An

    result = ask_slot(_state({}))["next_question"]

    assert "Hội An" in result


def test_a_destination_rewording_listing_every_entry_is_kept(monkeypatch) -> None:
    """The counterpart: the catalog check rejects omissions, not rewording."""
    monkeypatch.setattr(ask_slot_module, "_get_destination_names", lambda: ("Đà Nẵng", "Huế", "Hội An"))
    reworded = "Bạn đang nghĩ tới nơi nào — Đà Nẵng, Huế hay Hội An?"
    _use_rewording(monkeypatch, reworded)

    assert ask_slot(_state({}))["next_question"] == reworded


def test_every_slot_s_own_fallback_passes_the_rewording_validator(monkeypatch) -> None:
    """`_slot_question_is_usable` decides whether a REWORDING may be sent in
    the hardcoded question's place. If a slot's own hardcoded wording could
    not pass that bar, the bar is wrong — no rewording of it could ever be
    accepted, and the LLM call for that slot would be pure cost. This is the
    check that fails when a new slot is added with a renderer the validator
    silently rejects.
    """
    monkeypatch.setattr(ask_slot_module, "_get_destination_names", lambda: ("Đà Nẵng", "Huế"))

    for spec in SLOT_REGISTRY:
        pending = (spec.name, *spec.asked_with)
        question = _render_question(spec, pending, "vi")
        assert _slot_question_is_usable(question, spec, _slot_choices(spec, "vi")), spec.name


# --- Layer 2b: a revision is acknowledged above the next question ------------
#
# `revised_slots` is `apply_patch`'s output, seeded directly here so these
# stay unit tests of the rendering. `test_apply_patch.py` owns which paths
# land in it.


def _revised(travel_state: dict, *paths: str) -> TravelGraphState:
    state = _state(travel_state)
    state["revised_slots"] = list(paths)
    state["applied_changes"] = [{"path": path, "operation": "set"} for path in paths]
    return state


def test_a_corrected_destination_is_acknowledged_then_the_next_question_follows() -> None:
    """"đi Hà Nội" corrected to "đi Nha Trang": without this the reply is the
    next question alone, and nothing tells the user the correction landed."""
    travel_state = {**_ANSWERED, "destination": {"presence": "set", "value": "Nha Trang"}}
    state = _revised(travel_state, "destination")

    reply = ask_slot(state)["next_question"]

    assert reply.startswith("Đã cập nhật điểm đến thành Nha Trang.")
    assert reply.endswith(_render_question(*_pending_for(travel_state), "vi"))


def test_a_first_time_answer_is_not_announced_as_an_update() -> None:
    """`applied_changes` alone is not a revision — every ordinary intake turn
    applies something. Only `revised_slots` (an actual overwrite) earns the
    line, or "đã cập nhật" would precede every question in the flow."""
    state = _state(dict(_ANSWERED))
    state["applied_changes"] = [{"path": "people", "operation": "set"}]

    assert "\n\n" not in ask_slot(state)["next_question"]


def test_several_corrections_in_one_turn_are_listed_once_each() -> None:
    travel_state = {
        **_ANSWERED,
        "destination": {"presence": "set", "value": "Nha Trang"},
        "people": {"presence": "set", "value": 4},
    }
    state = _revised(travel_state, "destination", "people")

    reply = ask_slot(state)["next_question"]

    assert reply.startswith("Đã cập nhật điểm đến thành Nha Trang, số người thành 4.")


def test_the_budget_paths_are_named_once_and_never_echo_a_single_price() -> None:
    """All four budget paths share one label, so echoing a value would have
    to pick one end of a range and report it as the whole answer."""
    travel_state = {
        **_START_ANSWERED,
        "dates.end": {"presence": "set", "value": (date.today() + timedelta(days=34)).isoformat()},
        "budget.min": {"presence": "set", "value": 800_000},
        "budget.max": {"presence": "set", "value": 1_200_000},
    }
    state = _revised(travel_state, "budget.min", "budget.max")

    reply = ask_slot(state)["next_question"]

    assert reply.startswith("Đã cập nhật ngân sách.")
    assert "800000" not in reply


def test_an_opt_out_revision_names_the_slot_without_a_value() -> None:
    """Revising a real budget down to "no preference" leaves NOT_APPLICABLE,
    which has no value to quote back."""
    travel_state = {
        **_START_ANSWERED,
        "dates.end": {"presence": "set", "value": (date.today() + timedelta(days=34)).isoformat()},
        "budget.target": {"presence": "n/a", "value": None},
    }
    state = _revised(travel_state, "budget.target")

    assert ask_slot(state)["next_question"].startswith("Đã cập nhật ngân sách.")


def test_a_rejected_change_outranks_the_revision_line() -> None:
    """A turn that both landed something and had something refused has to
    report the refusal — that is the half the user must act on."""
    travel_state = {**_ANSWERED, "destination": {"presence": "set", "value": "Nha Trang"}}
    state = _revised(travel_state, "destination")
    spec = _spec_for(travel_state)
    state["rejected_changes"] = [{"path": spec.name, "reason": f"{spec.name}: expected YYYY-MM-DD"}]

    reply = ask_slot(state)["next_question"]

    assert "expected YYYY-MM-DD" in reply
    assert "Đã cập nhật" not in reply


def test_a_revised_path_with_no_user_facing_label_is_left_unmentioned() -> None:
    """`revised_slots` carries every overwritten path, not only intake slots.
    One the user never named has no honest label to announce, so the turn
    falls back to the bare question rather than inventing one."""
    travel_state = {**_ANSWERED, "hotel_preferences.radius_km": {"presence": "set", "value": 5}}
    state = _revised(travel_state, "hotel_preferences.radius_km")

    assert "\n\n" not in ask_slot(state)["next_question"]


def test_the_revision_line_is_translated() -> None:
    """Guards the `en` catalog entries: `t()` falls back to the msgid, so a
    missing translation does not fail loudly — it leaks Vietnamese into an
    English reply."""
    travel_state = {**_ANSWERED, "destination": {"presence": "set", "value": "Nha Trang"}}
    state = _revised(travel_state, "destination")
    state["language"] = "en"

    assert ask_slot(state)["next_question"].startswith("Updated destination to Nha Trang.")


def test_the_preferences_question_is_translated() -> None:
    """Same guard for the preferences slot's own question."""
    travel_state = {
        **_START_ANSWERED,
        "dates.end": {"presence": "set", "value": (date.today() + timedelta(days=34)).isoformat()},
        "budget.target": {"presence": "set", "value": 2_000_000},
    }
    spec, pending = _pending_for(travel_state)
    assert spec.prompt_key == "preferences"

    assert _render_question(spec, pending, "en").startswith("One last thing")


def test_the_preferences_question_offers_the_phrase_the_extractor_recognises() -> None:
    """Three surfaces have to name the same opt-out: this question, the
    extractor rule that maps it to `value: null`, and the frontend's
    `PREFERENCES_SKIP_PHRASE`. None can interpolate the others (a gettext
    msgid and a `.format()` template both need literal source text), so this
    is what keeps them from drifting — they already did once."""
    from src.agents.graph.prompts import PREFERENCES_OPT_OUT_PHRASE, build_extract_patch_prompt

    assert PREFERENCES_OPT_OUT_PHRASE in _render_preferences("vi")
    assert PREFERENCES_OPT_OUT_PHRASE in build_extract_patch_prompt(
        message="x",
        known_facts="",
        destination_choices="",
        pending_slots=(),
        today="2099-01-01",
        preference_labels="",
        companion_labels="",
        pace_labels="",
        day_rhythm_labels="",
    )


# --- Layer 2c: a value this system has no data for ---------------------------
#
# "đi rạch giá" produced only the destination question back, with nothing
# saying why — and, from the second attempt on, "Mình chưa hiểu rõ ý bạn",
# which blames comprehension for what is really a gap in the data. The user
# re-types a name that was never mistyped.


def _ungrounded(travel_state: dict, path: str, value: object, reason: str) -> TravelGraphState:
    state = _state(travel_state)
    state["rejected_changes"] = [
        {"path": path, "operation": "set", "value": value, "reason": reason}
    ]
    return state


def test_an_unsupported_destination_is_explained_not_silently_re_asked() -> None:
    state = _ungrounded({}, "destination", "Rạch Giá", UNKNOWN_DESTINATION_REASON)

    reply = ask_slot(state)["next_question"]

    assert reply.startswith("Rất tiếc, mình chưa hỗ trợ Rạch Giá.")
    assert "Dữ liệu chưa hợp lệ" not in reply  # a real place name is not malformed input


def test_a_second_attempt_still_explains_instead_of_blaming_the_user() -> None:
    """The regression that made the loop unescapable: with `destination`
    already pending from the previous turn, `_context_line` used to fall
    through to "Mình chưa hiểu rõ ý bạn" — and the user, told they were
    misunderstood, re-types the same unsupported name."""
    state = _ungrounded({}, "destination", "Rạch Giá", UNKNOWN_DESTINATION_REASON)
    state["missing_slots"] = ["destination"]

    reply = ask_slot(state)["next_question"]

    assert "chưa hiểu rõ ý bạn" not in reply
    assert "Rạch Giá" in reply


def test_an_unsupported_closed_label_gets_its_own_line() -> None:
    state = _ungrounded(dict(_ANSWERED), "preferences.pace", "siêu tốc", UNSUPPORTED_LABEL_REASON)

    assert ask_slot(state)["next_question"].startswith("Mình chưa hỗ trợ lựa chọn: siêu tốc.")


def test_a_rejected_list_value_is_joined_not_printed_as_a_repr() -> None:
    state = _ungrounded(dict(_ANSWERED), "preferences.themes", ["trekking", "lặn"], UNSUPPORTED_LABEL_REASON)

    reply = ask_slot(state)["next_question"]

    assert "trekking, lặn" in reply
    assert "[" not in reply


def test_the_grounding_line_outranks_the_generic_validation_wording() -> None:
    """Both kinds of rejection share `rejected_changes` now. The generic
    "Dữ liệu chưa hợp lệ: {reason}" rendering must never claim an
    unsupported-but-well-formed value was malformed."""
    state = _ungrounded({}, "destination", "Rạch Giá", UNKNOWN_DESTINATION_REASON)
    spec = _spec_for({})
    state["rejected_changes"].append(
        {"path": spec.name, "operation": "set", "value": "x", "reason": "expected YYYY-MM-DD"}
    )

    assert ask_slot(state)["next_question"].startswith("Rất tiếc, mình chưa hỗ trợ Rạch Giá.")


def test_the_grounding_line_is_translated() -> None:
    state = _ungrounded({}, "destination", "Rạch Giá", UNKNOWN_DESTINATION_REASON)
    state["language"] = "en"

    assert ask_slot(state)["next_question"].startswith("Sorry, Rạch Giá isn't supported yet.")

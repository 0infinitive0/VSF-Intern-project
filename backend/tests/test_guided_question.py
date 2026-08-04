from __future__ import annotations

from src.services.guided_question import (
    GuidedOption,
    GuidedQuestion,
    format_guided_question,
    resolve_guided_reply,
)


def _budget_like_question(*, required: bool = True, with_parser: bool = True) -> GuidedQuestion:
    return GuidedQuestion(
        prompt="Pick a tier:",
        options=(
            GuidedOption("Tier A", "a"),
            GuidedOption("Tier B", "b"),
            GuidedOption("Skip", None),
        ),
        free_text_parser=(lambda text: 999 if "custom" in text else None) if with_parser else None,
        required=required,
    )


def test_format_guided_question_renders_prompt_and_numbered_options():
    question = _budget_like_question()

    rendered = format_guided_question(question)

    assert rendered == "Pick a tier:\n1. Tier A\n2. Tier B\n3. Skip"


def test_resolve_guided_reply_single_numbered_pick():
    question = _budget_like_question()

    resolved, values = resolve_guided_reply(question, "2")

    assert resolved is True
    assert values == ("b",)


def test_resolve_guided_reply_multi_select_comma_separated():
    question = GuidedQuestion(
        prompt="Pick any:",
        options=(
            GuidedOption("X", "x"),
            GuidedOption("Y", "y"),
            GuidedOption("Z", "z"),
        ),
        required=False,
    )

    resolved, values = resolve_guided_reply(question, "1, 3")

    assert resolved is True
    assert values == ("x", "z")


def test_resolve_guided_reply_out_of_range_number_ignored():
    question = _budget_like_question()

    resolved, values = resolve_guided_reply(question, "99")

    # No option matched, no free-text success either ("99" doesn't contain "custom")
    assert resolved is False
    assert values == ()


def test_resolve_guided_reply_skip_option_wins_even_mixed_with_valid_numbers():
    question = _budget_like_question()

    resolved, values = resolve_guided_reply(question, "1,3")

    assert resolved is True
    assert values == ()


def test_resolve_guided_reply_free_text_parser_used_when_no_pure_number_pick():
    question = _budget_like_question()

    resolved, values = resolve_guided_reply(question, "give me a custom price")

    assert resolved is True
    assert values == (999,)


def test_resolve_guided_reply_digit_embedded_in_free_text_does_not_become_a_menu_pick():
    """A reply like "4 units" must not be misread as picking option 4 — only a
    reply that's ENTIRELY digits/separators is treated as a menu pick."""
    question = _budget_like_question()

    resolved, values = resolve_guided_reply(question, "2 custom")

    assert resolved is True
    assert values == (999,)  # resolved via free_text_parser, not option 2


def test_resolve_guided_reply_required_question_reprompts_when_unresolved():
    question = _budget_like_question(with_parser=False)

    resolved, values = resolve_guided_reply(question, "no idea")

    assert resolved is False
    assert values == ()


def test_resolve_guided_reply_optional_question_always_resolves():
    question = _budget_like_question(with_parser=False, required=False)

    resolved, values = resolve_guided_reply(question, "no idea")

    assert resolved is True
    assert values == ()


def test_resolve_guided_reply_empty_reply_does_not_crash():
    question = _budget_like_question(with_parser=False, required=False)

    resolved, values = resolve_guided_reply(question, "   ")

    assert resolved is True
    assert values == ()

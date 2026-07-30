from __future__ import annotations

from pathlib import Path

import src.services.trip_intake as trip_intake_module
from src.services.trip_intake import (
    DestinationOption,
    TripIntakeState,
    _ground_extracted_facts,
    _match_known_destination,
    destination_options_from_rows,
)

DESTINATIONS = ["Đà Nẵng", "Hồ Chí Minh", "Đắk Nông"]


def _mock_extraction(monkeypatch, responses: dict[str, dict]) -> None:
    """Monkeypatch the thin LLM call so `with_message()` tests are
    deterministic and make zero network/LLM calls. `responses` maps the
    exact message text to the raw dict the (fake) LLM would have returned;
    an unscripted message returns `{}` (fail-soft, same as a real failure)."""

    def fake(message, known_facts, destination_names, model=None):
        return responses.get(message, {})

    monkeypatch.setattr(trip_intake_module, "_llm_extract_intake_facts", fake)


# --- Pure grounding layer: _ground_extracted_facts / _match_known_destination ---
# Hand-built dicts simulating LLM output, no LLM/network call involved — the
# same convention as `normalize_day_themes()` in tests/test_trip_scheduler.py.


def test_ground_extracted_facts_accepts_matched_destination_and_formats_facts() -> None:
    grounded = _ground_extracted_facts(
        {
            "destination": "thanh pho da nang",
            "duration_days": 7,
            "people_count": 2,
            "preference_labels": ["biển", "made_up_label"],
            "skip_preferences": False,
        },
        DESTINATIONS,
    )
    assert grounded["destination"] == "Đà Nẵng"
    assert grounded["duration"] == "7 ngày"
    assert grounded["people"] == "2 người"
    assert grounded["preference_labels"] == ("biển",)  # hallucinated label dropped
    assert grounded["skip_preferences"] is False


def test_ground_extracted_facts_rejects_ungrounded_destination() -> None:
    """Regression guard: an LLM guess that doesn't match any real destination
    must never surface as a fact. This is the property that stands in for the
    old rule-based intake's guarantee against an LLM inventing/mangling a
    destination name (e.g. 'Đà Nẵng' -> 'Ễôi Đă Nông')."""
    grounded = _ground_extracted_facts({"destination": "Ễôi Đă Nông"}, DESTINATIONS)
    assert grounded["destination"] is None


def test_ground_extracted_facts_handles_missing_and_out_of_range_numbers() -> None:
    grounded = _ground_extracted_facts(
        {"duration_days": 0, "people_count": 999, "preference_labels": "not-a-list"},
        DESTINATIONS,
    )
    assert grounded["duration"] is None
    assert grounded["people"] is None
    assert grounded["preference_labels"] == ()


def test_match_known_destination_exact_and_alias_match() -> None:
    destinations = destination_options_from_rows(
        [{"name": "Hồ Chí Minh", "aliases": ["TP HCM", "TPHCM", "HCM", "Sài Gòn"]}]
    )
    assert _match_known_destination("tp hcm", destinations) == "Hồ Chí Minh"
    assert _match_known_destination("Sài Gòn", destinations) == "Hồ Chí Minh"


def test_match_known_destination_does_not_resolve_ambiguous_short_guesses() -> None:
    """A truncated single-word guess that is a substring of a destination name
    must not silently resolve to it — that would defeat the grounding guard
    just as surely as accepting an unmatched guess would. It should come back
    unmatched so the caller re-asks."""
    dests = ["Đà Nẵng", "Đà Lạt", "Đắk Nông"]
    assert _match_known_destination("Đà", dests) is None
    assert _match_known_destination("Nông", dests) is None


# --- with_message() integration: mocked LLM extraction, deterministic, no network ---


def test_sequential_intake_uses_mocked_llm_facts_across_turns(monkeypatch) -> None:
    _mock_extraction(
        monkeypatch,
        {
            "tôi muốn đi chơi ở đà nẵng": {"destination": "Đà Nẵng"},
            "1 tuần": {"duration_days": 7},
            "tôi đi cùng vợ của tôi": {"people_count": 2},
            "tập trung tắm biển và du lịch lịch sử": {"preference_labels": ["biển", "lịch sử"]},
        },
    )
    state = TripIntakeState()

    state = state.with_message("tôi muốn đi chơi ở đà nẵng", DESTINATIONS)
    assert state.destination == "Đà Nẵng"
    assert state.next_question() == "Bạn dự định đi trong bao lâu?"

    state = state.with_message("1 tuần", DESTINATIONS)
    assert state.duration == "7 ngày"
    assert state.next_question() == "Chuyến đi có bao nhiêu người?"

    state = state.with_message("tôi đi cùng vợ của tôi", DESTINATIONS)
    assert "Bạn có yêu cầu hay lưu ý đặc biệt nào cho chuyến đi" in state.next_question()

    state = state.with_message("tập trung tắm biển và du lịch lịch sử", DESTINATIONS)
    assert state.is_complete
    assert state.next_question() is None
    assert state.tool_arguments() == {
        "destination": "Đà Nẵng",
        "duration": "7 ngày",
        "people": "2 người",
        "preferences": "biển, lịch sử, tập trung tắm biển và du lịch lịch sử",
    }


def test_complete_single_message_preserves_optional_preferences_without_requiring_them(monkeypatch) -> None:
    _mock_extraction(
        monkeypatch,
        {
            "Hai người đi Đà Nẵng 3 ngày, thích biển và văn hóa": {
                "destination": "Đà Nẵng",
                "duration_days": 3,
                "people_count": 2,
                "preference_labels": ["biển", "văn hóa"],
            },
            "không": {"skip_preferences": True},
        },
    )
    state = TripIntakeState().with_message(
        "Hai người đi Đà Nẵng 3 ngày, thích biển và văn hóa", DESTINATIONS
    )
    assert "Bạn có yêu cầu hay lưu ý đặc biệt" in state.next_question()

    state = state.with_message("không", DESTINATIONS)
    assert state.is_complete
    assert state.destination == "Đà Nẵng"
    assert state.duration == "3 ngày"
    assert state.people == "2 người"
    assert state.preferences == ("biển", "văn hóa")


def test_negative_reply_is_not_stored_as_a_preference_even_if_llm_extraction_fails(monkeypatch) -> None:
    """Regression guard for the skip_preferences fail-soft case: when the LLM
    call fails/returns nothing, a plain 'không' must still be recognized as a
    skip via the deterministic safety-net set, not stored as a literal
    preference string."""
    _mock_extraction(monkeypatch, {})  # every call fails soft to {}

    state = TripIntakeState(destination="Đà Nẵng", duration="3 ngày", people="2 người")
    state = state.with_message("không", DESTINATIONS)
    assert state.is_complete
    assert state.preferences == ()


def test_negative_response_safety_net_does_not_override_a_healthy_llm(monkeypatch) -> None:
    """The deterministic decline check only applies when extraction produced
    nothing (LLM/network failure). When the LLM is healthy and correctly says
    skip_preferences=False for a real preference that happens to start with
    'không cần', the safety net must not discard it."""
    message = "không cần khách sạn sang trọng, chỉ thích tắm biển và ăn hải sản"
    _mock_extraction(
        monkeypatch,
        {message: {"skip_preferences": False, "preference_labels": ["biển"]}},
    )
    state = TripIntakeState(destination="Đà Nẵng", duration="3 ngày", people="2 người")
    state = state.with_message(message, DESTINATIONS)
    assert message in state.preferences


def test_negative_response_safety_net_handles_punctuation_and_particles(monkeypatch) -> None:
    """Fail-soft path: common real-world decline phrasing (trailing period,
    exclamation mark, or the 'ạ' politeness particle) must still be
    recognized, not just the bare 'không'."""
    _mock_extraction(monkeypatch, {})  # every call fails soft to {}

    for message in ("Không.", "không!", "Không ạ"):
        state = TripIntakeState(destination="Đà Nẵng", duration="3 ngày", people="2 người")
        state = state.with_message(message, DESTINATIONS)
        assert state.preferences == (), f"expected no preference stored for {message!r}"


def test_destination_is_taken_from_grounded_facts_not_an_ungrounded_model_guess(monkeypatch) -> None:
    """Regression guard: a simulated LLM mangling of the destination must
    never reach `tool_arguments()['destination']` — the same failure mode the
    original rule-based intake was built to prevent."""
    _mock_extraction(
        monkeypatch,
        {
            "Đà Nẵng, 2 người, 4 ngày": {
                "destination": "Ễôi Đă Nông",
                "duration_days": 4,
                "people_count": 2,
            },
        },
    )
    state = TripIntakeState().with_message("Đà Nẵng, 2 người, 4 ngày", DESTINATIONS)
    assert state.destination is None
    assert state.next_question() == "Bạn muốn đi đâu?"


def test_hcm_abbreviation_does_not_repeat_the_destination_question(monkeypatch) -> None:
    destinations = destination_options_from_rows(
        [
            {
                "name": "Hồ Chí Minh",
                "aliases": ["TP HCM", "TPHCM", "HCM", "Sài Gòn", "Saigon"],
            }
        ]
    )
    assert destinations == (
        DestinationOption(
            name="Hồ Chí Minh",
            aliases=("TP HCM", "TPHCM", "HCM", "Sài Gòn", "Saigon"),
        ),
    )

    _mock_extraction(
        monkeypatch,
        {"tôi muốn đi chơi tp hcm 3 ngày": {"destination": "Hồ Chí Minh", "duration_days": 3}},
    )
    state = TripIntakeState().with_message("tôi muốn đi chơi tp hcm 3 ngày", destinations)

    assert state.destination == "Hồ Chí Minh"
    assert state.duration == "3 ngày"
    assert state.next_question() == "Chuyến đi có bao nhiêu người?"


def test_destination_alias_schema_and_terminal_loader_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    migration = (
        root / "scripts" / "migrations" / "20260728_add_destination_aliases.sql"
    ).read_text(encoding="utf-8")
    schema = (root / "scripts" / "database_schema.sql").read_text(encoding="utf-8")
    planner = (root / "src" / "cli" / "trip_builder_svc.py").read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS aliases TEXT[]" in migration
    assert "ALTER COLUMN aliases SET DEFAULT '{}'::TEXT[]" in migration
    assert "ALTER COLUMN aliases SET NOT NULL" in migration
    assert "UPDATE destinations" in migration
    assert "TP HCM" in migration
    assert "aliases TEXT[] NOT NULL DEFAULT '{}'::TEXT[]" in schema
    assert '.select("name, aliases")' in planner
    assert "destination_options_from_rows(response.data or [])" in planner

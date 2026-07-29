from pathlib import Path

from src.services.trip_intake import (
    DestinationOption,
    TripIntakeState,
    destination_options_from_rows,
)

DESTINATIONS = ["Đà Nẵng", "Hồ Chí Minh", "Đắk Nông"]


def test_sequential_vietnamese_intake_uses_verified_facts_without_asking_again() -> None:
    state = TripIntakeState()

    state = state.with_message("tôi muốn đi chơi ở đà nẵng", DESTINATIONS)
    assert state.destination == "Đà Nẵng"
    assert state.next_question() == "Bạn dự định đi trong bao lâu?"

    state = state.with_message("1 tuần", DESTINATIONS)
    assert state.duration == "1 tuần"
    assert state.next_question() == "Chuyến đi có bao nhiêu người?"

    state = state.with_message("tôi đi cùng vợ của tôi", DESTINATIONS)

    assert state.is_complete
    assert state.next_question() is None
    assert state.tool_arguments() == {
        "destination": "Đà Nẵng",
        "duration": "1 tuần",
        "people": "2 người",
        "preferences": "",
    }


def test_complete_single_message_preserves_optional_preferences_without_requiring_them() -> None:
    state = TripIntakeState().with_message(
        "Hai người đi Đà Nẵng 3 ngày, thích biển và văn hóa",
        DESTINATIONS,
    )

    assert state.is_complete
    assert state.destination == "Đà Nẵng"
    assert state.duration == "3 ngày"
    assert state.people == "2 người"
    assert state.preferences == ("biển", "văn hóa")


def test_destination_is_taken_from_user_input_not_a_corrupted_model_argument() -> None:
    state = TripIntakeState().with_message(
        "Đà Nẵng, 2 người, 4 ngày",
        DESTINATIONS,
    )

    arguments = state.tool_arguments()

    assert arguments["destination"] == "Đà Nẵng"
    assert arguments["destination"] != "Ễôi Đă Nông"


def test_hcm_abbreviation_does_not_repeat_the_destination_question() -> None:
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

    state = TripIntakeState().with_message(
        "tôi muốn đi chơi tp hcm 3 ngày",
        destinations,
    )

    assert state.destination == "Hồ Chí Minh"
    assert state.duration == "3 ngày"
    assert state.next_question() == "Chuyến đi có bao nhiêu người?"

    state = state.with_message("tp hcm", destinations)

    assert state.destination == "Hồ Chí Minh"
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

from src.services.trip_intake import TripIntakeState

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

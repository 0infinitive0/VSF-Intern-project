from src.services.session_context import SessionContextData


def test_session_context_defaults_to_trip_info_with_safe_empty_filters():
    context = SessionContextData()

    assert context.active_step == "trip_info"
    assert context.dates.start_date is None
    assert context.guests.adults == 1
    assert context.price_range.currency == "VND"
    assert context.excluded_hotel_ids == []


def test_session_context_merges_only_supported_preference_updates():
    context = SessionContextData(preferences=["Gần biển", "Bể bơi"])

    updated = context.merge_preferences(
        add_preferences=["Ăn sáng miễn phí", "Gần biển"],
        remove_preferences=["Bể bơi"],
    )

    assert updated.preferences == ["Gần biển", "Ăn sáng miễn phí"]

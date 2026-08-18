"""The Q&A node's hotel lookup — the state key it reads, and reaching it.

`query_hotel` / `query_hotel_rooms` read `state["hotel_options"]`, which
`TravelGraphState` has never defined. Every call therefore fell into the
"no hotel list" branch, so every question about a hotel already on screen
came back as "mình không thấy danh sách khách sạn hiện tại" — with the cards
visible beside the answer. Two separate things had to be true for the tools
to work, and both are pinned here: the key has to be the one that actually
holds the cards, and the subgraph's schema has to let that key through.
"""

from __future__ import annotations

from src.agents.graph.nodes.qa_node import QAState
from src.agents.graph.state import TravelGraphState
from src.agents.tools.shown_hotels import shown_hotel_options


def test_the_old_key_is_not_part_of_the_graph_state():
    """Guards the root cause itself. If someone adds a `hotel_options` key
    to TravelGraphState later, this test failing is the signal to re-check
    which source these tools should be reading."""
    assert "hotel_options" not in TravelGraphState.__annotations__
    assert "previous_hotel_options" in TravelGraphState.__annotations__


def test_cards_are_read_from_the_key_that_survives_a_turn_reset():
    """`previous_hotel_options` deliberately outlives `load_context`, which
    is what makes a question two turns after the search answerable."""
    state = {"previous_hotel_options": [{"rank": 1, "name": "DLG Hotel Danang"}]}

    assert [option["name"] for option in shown_hotel_options(state)] == ["DLG Hotel Danang"]


def test_a_question_in_the_same_turn_as_the_search_still_resolves():
    """On the search turn itself the cards are still only in task_results."""
    state = {
        "task_results": [
            {"worker": "hotel_node", "hotel_search_result": {"options": [{"rank": 1, "name": "Mangata"}]}}
        ]
    }

    assert [option["name"] for option in shown_hotel_options(state)] == ["Mangata"]


def test_the_durable_list_wins_over_a_stale_task_result():
    state = {
        "previous_hotel_options": [{"rank": 1, "name": "Newest"}],
        "task_results": [{"hotel_search_result": {"options": [{"rank": 1, "name": "Older"}]}}],
    }

    assert [option["name"] for option in shown_hotel_options(state)] == ["Newest"]


def test_no_search_yet_is_an_empty_list_not_an_error():
    """The honest case: nothing has been searched, so there is nothing to
    answer from. Distinct from the bug, where cards existed but were unreachable."""
    assert shown_hotel_options({}) == []
    assert shown_hotel_options({"previous_hotel_options": []}) == []
    assert shown_hotel_options(None) == []


def test_malformed_entries_are_skipped_rather_than_crashing_the_turn():
    state = {"previous_hotel_options": ["not-a-dict", {"rank": 1, "name": "Real"}]}

    assert [option["name"] for option in shown_hotel_options(state)] == ["Real"]


def test_the_subgraph_schema_lets_the_cards_through():
    """A subgraph only receives the parent keys its own schema declares. The
    tools can read `previous_hotel_options` only because QAState names it."""
    assert "previous_hotel_options" in QAState.__annotations__
    assert "language" in QAState.__annotations__


def test_the_write_contract_is_not_widened():
    """Read access only: the worker channels stay structurally unreachable."""
    for channel in ("travel_state", "pending_tasks", "task_results"):
        assert channel not in QAState.__annotations__


# ---------------------------------------------------------------------------
# Amenity ids never reach the model.
#
# The Q&A tools handed `amenities` / `room_facilities` to the model as raw
# canonical ids, and it read them back out verbatim -- "khách sạn số 1 có bể
# bơi (swimming_pool), onsen (hot_spring_bath)". Same raw-id leak already
# fixed on the hotel-search reply path, arriving through a different door.
# ---------------------------------------------------------------------------


def _stub_catalog(monkeypatch):
    from src.services.amenity_catalog import AmenityCatalogEntry
    from src.agents.tools import shown_hotels

    monkeypatch.setattr(
        shown_hotels,
        "all_approved_amenities",
        lambda: (
            AmenityCatalogEntry(id="swimming_pool", label="Hồ bơi", label_en="Swimming Pool", match_keywords=()),
            AmenityCatalogEntry(id="hot_spring_bath", label="Tắm onsen", label_en="Hot Spring Bath", match_keywords=()),
        ),
    )


def test_ids_are_resolved_to_the_labels_the_user_already_sees(monkeypatch):
    from src.agents.tools.shown_hotels import labelled_amenities

    _stub_catalog(monkeypatch)

    assert labelled_amenities(["swimming_pool", "hot_spring_bath"]) == ["Hồ bơi", "Tắm onsen"]


def test_english_sessions_get_english_labels(monkeypatch):
    from src.agents.tools.shown_hotels import labelled_amenities

    _stub_catalog(monkeypatch)

    assert labelled_amenities(["swimming_pool"], language="en") == ["Swimming Pool"]


def test_an_id_missing_from_the_catalog_is_kept_rather_than_dropped(monkeypatch):
    """It is still a real fact about the hotel; an ugly label beats silence."""
    from src.agents.tools.shown_hotels import labelled_amenities

    _stub_catalog(monkeypatch)

    assert labelled_amenities(["swimming_pool", "unlisted_thing"]) == ["Hồ bơi", "unlisted_thing"]


def test_a_catalog_outage_never_fails_the_question(monkeypatch):
    from src.agents.tools import shown_hotels

    def _down():
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(shown_hotels, "all_approved_amenities", _down)

    assert shown_hotels.labelled_amenities(["swimming_pool"]) == ["swimming_pool"]


def test_non_list_input_is_tolerated(monkeypatch):
    from src.agents.tools.shown_hotels import labelled_amenities

    _stub_catalog(monkeypatch)

    assert labelled_amenities(None) == []
    assert labelled_amenities("swimming_pool") == []

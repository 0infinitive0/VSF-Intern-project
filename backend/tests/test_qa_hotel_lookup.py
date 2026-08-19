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


# ---------------------------------------------------------------------------
# The two context tools: the shortlist, and the itinerary.
#
# qa_node could fetch ONE named hotel and had no access to trip_data at all,
# so "which of these is cheapest?" and "what's on day 2?" had no source to
# answer from. The model's usual escape was to ask the user to narrow down
# first, which costs a turn to learn something already on their screen.
# ---------------------------------------------------------------------------


def _tool_text(command):
    """The ToolMessage content a tool hands back to the model."""
    return command.update["messages"][0].content


def _Runtime(state):
    """A real ToolRuntime — `@tool` validates the type, so a stub is rejected."""
    from langchain.tools import ToolRuntime

    return ToolRuntime(
        state=state,
        context=None,
        config={},
        stream_writer=lambda _chunk: None,
        tool_call_id="call_1",
        store=None,
        tools=[],
    )


def test_the_shortlist_tool_returns_every_card_with_comparable_fields(monkeypatch):
    from src.agents.tools.get_hotel_options import get_hotel_options

    _stub_catalog(monkeypatch)
    state = {
        "language": "vi",
        "previous_hotel_options": [
            {"rank": 1, "name": "Alpha", "average_nightly_price": 1_500_000,
             "review_score": 8.8, "amenities": ["swimming_pool"], "area_name": "Hải Châu"},
            {"rank": 2, "name": "Beta", "average_nightly_price": 900_000, "review_score": 9.1},
        ],
    }

    text = _tool_text(get_hotel_options.invoke({"runtime": _Runtime(state)}))

    assert "Alpha" in text and "Beta" in text
    assert "1500000" in text.replace(",", "") or "1_500_000" in text
    # Labels, never canonical ids — same leak already fixed on the other tools.
    assert "Hồ bơi" in text
    assert "swimming_pool" not in text


def test_the_shortlist_never_truncates_amenities(monkeypatch):
    """`amenities` is stored in no meaningful order, so any cap drops
    arbitrary facts. Capped at 8, "hồ bơi" fell past the cut and the model
    reported four hotels as having no pool while "Hồ bơi" was printed on
    every one of their cards."""
    from src.agents.tools.get_hotel_options import get_hotel_options

    monkeypatch.setattr(
        "src.agents.tools.get_hotel_options.labelled_amenities",
        lambda tags, language="vi": [f"tien-nghi-{i}" for i in range(20)] + ["Hồ bơi"],
    )
    state = {"previous_hotel_options": [{"rank": 1, "name": "Alpha", "amenities": ["x"]}]}

    text = _tool_text(get_hotel_options.invoke({"runtime": _Runtime(state)}))

    assert "Hồ bơi" in text
    assert "tien-nghi-19" in text


def test_the_shortlist_tool_is_honest_before_any_search(monkeypatch):
    from src.agents.tools.get_hotel_options import get_hotel_options

    _stub_catalog(monkeypatch)

    text = _tool_text(get_hotel_options.invoke({"runtime": _Runtime({"language": "vi"})}))

    assert "Chưa có danh sách khách sạn" in text


def test_a_card_missing_its_rank_is_still_referable_by_position(monkeypatch):
    from src.agents.tools.get_hotel_options import get_hotel_options

    _stub_catalog(monkeypatch)
    state = {"previous_hotel_options": [{"name": "NoRank"}]}

    assert '"rank": 1' in _tool_text(get_hotel_options.invoke({"runtime": _Runtime(state)}))


def test_the_plan_tool_returns_the_schedule():
    from src.agents.tools.get_trip_plan import get_trip_plan

    state = {
        "language": "vi",
        "trip_data": {
            "hotel": {"name": "DLG Hotel Danang", "star_rating": 5, "currency": "VND"},
            "itineraries": [{"status": "Draft", "duration_days": 1, "start_date": "2026-07-03"}],
            "itinerary_items": [
                {"day_number": 1, "order_index": 1, "activity": "Bãi biển Mỹ Khê",
                 "start_time": "08:15", "route_to_next": {"distance_km": 1.2, "duration_mins": 9,
                                                          "polyline": "SHOULD_NOT_LEAK"}},
            ],
        },
    }

    text = _tool_text(get_trip_plan.invoke({"runtime": _Runtime(state)}))

    assert "Bãi biển Mỹ Khê" in text
    assert "DLG Hotel Danang" in text
    assert "08:15" in text
    # "how far is it" needs the leg; the map polyline is pure token weight.
    assert "1.2" in text
    assert "SHOULD_NOT_LEAK" not in text


def test_the_plan_tool_is_honest_before_an_itinerary_exists():
    from src.agents.tools.get_trip_plan import get_trip_plan

    text = _tool_text(get_trip_plan.invoke({"runtime": _Runtime({"language": "vi", "trip_data": {}})}))

    assert "Chưa có lịch trình" in text


def test_both_context_tools_are_wired_into_the_node():
    from src.agents.graph.nodes.qa_node import QA_TOOLS, QAState

    assert {tool.name for tool in QA_TOOLS} >= {"get_hotel_options", "get_trip_plan"}
    # get_trip_plan can only work if the schema lets trip_data cross.
    assert "trip_data" in QAState.__annotations__


# ---------------------------------------------------------------------------
# A read-only turn never reaches a worker that writes.
#
# With no pending tasks the supervisor fell through to its LLM branch, which
# is unconstrained exactly BECAUSE the queue is empty -- and an unconstrained
# choice includes itinerary_node. Asking "ngày 3 tôi làm gì?" rebuilt the
# whole trip: day 1's attraction silently changed and the reply never said
# so. The extractor was correct throughout (general_question, empty patch),
# so this could only be fixed at the routing layer.
# ---------------------------------------------------------------------------


def _supervisor_state(**extra):
    from src.agents.graph.state import initial_graph_state

    state = initial_graph_state("t1")
    state.update({"pending_tasks": [], "task_results": [], "trip_data": {"itineraries": [{}]}})
    state.update(extra)
    return state


def test_a_question_is_routed_to_qa_node_without_asking_an_llm(monkeypatch):
    from src.agents.graph.nodes import supervisor as supervisor_module

    def _unreachable(*_a, **_k):
        raise AssertionError("a read-only turn must not reach the LLM router")

    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable)

    decision = supervisor_module.supervisor(_supervisor_state(intent="general_question"))

    assert decision["next_worker"] == "qa_node"
    assert decision["routing_source"] == "read_only_intent"


def test_a_stating_turn_still_reaches_the_normal_router(monkeypatch):
    """The gate keys on intent alone, so an edit is untouched by it."""
    from src.agents.graph.nodes import supervisor as supervisor_module

    called = {"llm": False}

    def _fake_llm(*_a, **_k):
        called["llm"] = True
        raise RuntimeError("stop here -- reaching the LLM is the assertion")

    monkeypatch.setattr(supervisor_module, "get_fast_llm", _fake_llm)

    supervisor_module.supervisor(_supervisor_state(intent="update_itinerary"))

    assert called["llm"] is True


# ---------------------------------------------------------------------------
# Database vocabulary never reaches the traveller.
#
# The tools serialized raw table rows, and the model reports the shape it is
# handed: asked whether a family of four fits, it answered "không có loại
# phòng nào có trường max_guests = 4" and "nhiều phòng có max_guests = null"
# -- a column name and a JSON literal, to a parent choosing a room.
# ---------------------------------------------------------------------------


def test_unknown_values_are_omitted_rather_than_sent_as_null():
    from src.agents.tools.shown_hotels import without_unknowns

    cleaned = without_unknowns({"room": "Suite", "sleeps": None, "view": "", "facilities": []})

    assert cleaned == {"room": "Suite"}


def test_real_zeroes_and_falses_survive():
    """Absent means unknown; 0 is an answer, not a gap."""
    from src.agents.tools.shown_hotels import without_unknowns

    assert without_unknowns({"sleeps": 0, "refundable": False}) == {"sleeps": 0, "refundable": False}


def test_the_hotel_tool_emits_no_column_names(monkeypatch):
    from src.agents.tools.query_hotel import query_hotel

    _stub_catalog(monkeypatch)
    state = {
        "language": "vi",
        "previous_hotel_options": [
            {"rank": 1, "name": "Liberty", "lowest_price": 2_097_309, "star_rating": 4.5,
             "amenities": ["swimming_pool"], "description": None, "covered_meals": []},
        ],
    }

    text = _tool_text(query_hotel.invoke({"hotel_identifier": "1", "runtime": _Runtime(state)}))

    for leaked in ("lowest_price", "star_rating", "covered_meals", "matched_room_names", "null"):
        assert leaked not in text, f"{leaked!r} reached the model"
    # Keys are Vietnamese here, so a quoted key still reads as prose.
    assert "giá mỗi đêm từ" in text
    assert "Liberty" in text and "2097309" in text.replace(",", "").replace(".", "")


def _hotel_state(*, language="vi", **extra):
    state = {
        "language": language,
        "previous_hotel_options": [{"rank": 1, "name": "Liberty", "id": "h1"}],
        "previous_hotel_search_context": {
            "destination_id": "d1", "start_date": "2026-07-01", "end_date": "2026-07-04", "people": "4",
        },
    }
    state.update(extra)
    return state


def test_a_room_with_no_recorded_capacity_carries_no_null(monkeypatch):
    """The exact shape behind "nhiều phòng có max_guests = null"."""
    from src.agents.tools import query_hotel_rooms as rooms_module

    _stub_catalog(monkeypatch)
    monkeypatch.setattr(
        rooms_module,
        "get_hotel_detail",
        lambda *_a, **_k: {"rooms": [
            {"name": "Executive Twin", "max_guests": None, "room_size_sqm": 27,
             "bed_description": "2 giường đơn", "view": None, "room_facilities": ["swimming_pool"],
             "price": None, "available_room_count": 3},
        ]},
    )

    text = _tool_text(rooms_module.query_hotel_rooms.invoke({"hotel_identifier": "1", "runtime": _Runtime(_hotel_state())}))

    for leaked in ("max_guests", "room_size_sqm", "bed_description", "room_facilities",
                   "null", "sleeps", "facilities"):
        assert leaked not in text, f"{leaked!r} reached the model"
    assert "Executive Twin" in text
    assert "Hồ bơi" in text
    # The unknown capacity is absent entirely, not rendered as an empty key.
    assert "số khách" not in text
    assert "giường" in text


def test_english_sessions_get_english_keys(monkeypatch):
    from src.agents.tools import query_hotel_rooms as rooms_module

    _stub_catalog(monkeypatch)
    monkeypatch.setattr(
        rooms_module,
        "get_hotel_detail",
        lambda *_a, **_k: {"rooms": [
            {"name": "Suite", "max_guests": 2, "price": None, "available_room_count": 1},
        ]},
    )

    text = _tool_text(
        rooms_module.query_hotel_rooms.invoke(
            {"hotel_identifier": "1", "runtime": _Runtime(_hotel_state(language="en"))}
        )
    )

    assert '"sleeps": 2' in text
    assert "max_guests" not in text


# ---------------------------------------------------------------------------
# Price and availability -- Errors #3 from the family-persona QA run.
#
# The tool used to select only name/max_guests/room_size_sqm/bed_description/
# view/room_facilities from the `rooms` table: no price column, no
# availability column. Asked how much a room cost, it said the data wasn't
# returned while the UI showed 2.097.309 ₫ for the same room, and it listed
# sold-out rooms as options with no indication they could not be booked.
# `get_hotel_detail` is the exact function `GET /hotels/{id}` uses to build
# those cards, so reusing it makes the two sources structurally the same.
# ---------------------------------------------------------------------------


def test_price_and_availability_reach_the_model(monkeypatch):
    from src.agents.tools import query_hotel_rooms as rooms_module

    _stub_catalog(monkeypatch)
    captured = {}

    def _fake_detail(hotel_id, check_in, check_out):
        captured["args"] = (hotel_id, check_in, check_out)
        return {"rooms": [
            {"name": "Suite", "max_guests": 2,
             "price": {"amount": 2_097_309, "currency": "VND"}, "available_room_count": 6},
        ]}

    monkeypatch.setattr(rooms_module, "get_hotel_detail", _fake_detail)

    text = _tool_text(rooms_module.query_hotel_rooms.invoke({"hotel_identifier": "1", "runtime": _Runtime(_hotel_state())}))

    assert "2097309" in text.replace(",", "").replace(".", "")
    assert "Còn 6 phòng" in text
    # The dates from previous_hotel_search_context reached get_hotel_detail.
    from datetime import date
    assert captured["args"] == ("h1", date(2026, 7, 1), date(2026, 7, 4))


def test_a_sold_out_room_is_reported_sold_out_not_omitted(monkeypatch):
    """The bug wasn't just "no price" -- it was recommending rooms nobody
    could book. available_room_count == 0 must read as sold out, in words."""
    from src.agents.tools import query_hotel_rooms as rooms_module

    _stub_catalog(monkeypatch)
    monkeypatch.setattr(
        rooms_module,
        "get_hotel_detail",
        lambda *_a, **_k: {"rooms": [
            {"name": "Presidential Suite", "price": None, "available_room_count": 0},
        ]},
    )

    text = _tool_text(rooms_module.query_hotel_rooms.invoke({"hotel_identifier": "1", "runtime": _Runtime(_hotel_state())}))

    assert "Hết phòng" in text
    assert "Presidential Suite" in text


def test_no_price_row_reads_as_price_on_request_not_a_missing_field(monkeypatch):
    from src.agents.tools import query_hotel_rooms as rooms_module

    _stub_catalog(monkeypatch)
    monkeypatch.setattr(
        rooms_module,
        "get_hotel_detail",
        lambda *_a, **_k: {"rooms": [{"name": "Villa", "price": None, "available_room_count": 2}]},
    )

    text = _tool_text(rooms_module.query_hotel_rooms.invoke({"hotel_identifier": "1", "runtime": _Runtime(_hotel_state())}))

    assert "Giá theo yêu cầu" in text


def test_missing_search_dates_still_returns_rooms_without_crashing(monkeypatch):
    """A session old enough to predate this fix, or a turn where the search
    context genuinely never landed -- get_hotel_detail must be called with
    (None, None) rather than the tool raising."""
    from src.agents.tools import query_hotel_rooms as rooms_module

    _stub_catalog(monkeypatch)
    captured = {}

    def _fake_detail(hotel_id, check_in, check_out):
        captured["args"] = (hotel_id, check_in, check_out)
        return {"rooms": [{"name": "Suite", "price": None, "available_room_count": 1}]}

    monkeypatch.setattr(rooms_module, "get_hotel_detail", _fake_detail)
    state = {"language": "vi", "previous_hotel_options": [{"rank": 1, "name": "Liberty", "id": "h1"}]}

    text = _tool_text(rooms_module.query_hotel_rooms.invoke({"hotel_identifier": "1", "runtime": _Runtime(state)}))

    assert captured["args"] == ("h1", None, None)
    assert "Suite" in text


def test_dates_fall_back_to_the_built_itinerary_when_search_context_is_stale(monkeypatch):
    from datetime import date
    from src.agents.tools import query_hotel_rooms as rooms_module

    _stub_catalog(monkeypatch)
    captured = {}

    def _fake_detail(hotel_id, check_in, check_out):
        captured["args"] = (hotel_id, check_in, check_out)
        return {"rooms": [{"name": "Suite", "price": None, "available_room_count": 1}]}

    monkeypatch.setattr(rooms_module, "get_hotel_detail", _fake_detail)
    state = {
        "language": "vi",
        "previous_hotel_options": [{"rank": 1, "name": "Liberty", "id": "h1"}],
        "trip_data": {"itineraries": [{"start_date": "2026-08-01", "end_date": "2026-08-05"}]},
    }

    rooms_module.query_hotel_rooms.invoke({"hotel_identifier": "1", "runtime": _Runtime(state)})

    assert captured["args"] == ("h1", date(2026, 8, 1), date(2026, 8, 5))

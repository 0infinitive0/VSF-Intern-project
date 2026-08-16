"""`respond` node — `_budget_from_travel_state` mapping onto IntakeStatus,
`_derive_stage`, and the stage-gated `suggestions`/`all_preferences`/
`active_preferences`/`compound_*` fields (phase-17).

Presence-aware budget echo: an explicit "no preference" answer sets
budget.target to Presence.NOT_APPLICABLE, distinct from a slot nobody has
answered yet (Presence.UNKNOWN) -- both must map to different
IntakeStatus.budget_skipped/min_price/max_price outcomes, or the frontend's
intake widget re-asks a budget the user already answered via plain chat.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage

import src.agents.graph.nodes.respond as respond_module
import src.services.amenity_catalog as amenity_catalog_module
from src.agents.graph.nodes.respond import _budget_from_travel_state, respond
from src.agents.graph.state import TravelGraphState, initial_graph_state
from src.domain.travel_state import TravelState, apply_patch
from src.services.trip_formatter import format_trip_summary_reply


def _state(**overrides: Any) -> TravelGraphState:
    state = initial_graph_state("t1")
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


def _hotel_task_results() -> list[dict[str, Any]]:
    return [
        {
            "worker": "hotel_node",
            "status": "ok",
            "reply": "Mình tìm được 1 khách sạn phù hợp.",
            "hotel_search_result": {
                "options": [{"id": "h1", "name": "Hotel A"}],
                "active_preferences": [],
            },
        }
    ]


def _seeded(changes: list[dict]) -> TravelState:
    return apply_patch(TravelState(), changes).state


class TestBudgetFromTravelState:
    def test_unanswered_budget_is_neither_skipped_nor_priced(self):
        min_price, max_price, skipped = _budget_from_travel_state(TravelState())
        assert (min_price, max_price, skipped) == (None, None, False)

    def test_explicit_no_preference_sets_skipped_without_a_price(self):
        state = _seeded([{"path": "budget.target", "operation": "set", "value": None}])
        min_price, max_price, skipped = _budget_from_travel_state(state)
        assert (min_price, max_price, skipped) == (None, None, True)

    def test_explicit_range_surfaces_min_and_max_without_skipped(self):
        state = _seeded(
            [
                {"path": "budget.min", "operation": "set", "value": 800_000},
                {"path": "budget.max", "operation": "set", "value": 2_500_000},
            ]
        )
        min_price, max_price, skipped = _budget_from_travel_state(state)
        assert (min_price, max_price, skipped) == (800_000, 2_500_000, False)

    def test_bare_target_answers_neither_range_nor_skip(self):
        # A single preferred price (no explicit min/max range, no opt-out) —
        # deliberately not forced into the range shape (respond.py's own
        # docstring on _budget_from_travel_state explains why).
        state = _seeded([{"path": "budget.target", "operation": "set", "value": 1_000_000}])
        min_price, max_price, skipped = _budget_from_travel_state(state)
        assert (min_price, max_price, skipped) == (None, None, False)


class TestDeriveStage:
    def test_missing_slots_is_intake(self):
        state = _state(missing_slots=["destination"])
        assert respond_module._derive_stage(state, hotel_options=[]) == "intake"

    def test_trip_data_outranks_hotel_options(self):
        state = _state(trip_data={"destination": "Đà Nẵng"})
        assert respond_module._derive_stage(state, hotel_options=[{"id": "h1"}]) == "planned"

    def test_hotel_options_with_no_trip_data_is_hotel_options(self):
        state = _state()
        assert respond_module._derive_stage(state, hotel_options=[{"id": "h1"}]) == "hotel_options"

    def test_empty_state_is_intake(self):
        assert respond_module._derive_stage(_state(), hotel_options=[]) == "intake"

    def test_every_reachable_stage_is_a_valid_chat_stage(self):
        # ChatStage (schemas.py) also allows "finalized"/"modified"/"error" —
        # none of the three has a graph producer yet, so they must never
        # appear here (phase-17's vocabulary-bound requirement).
        reachable = {
            respond_module._derive_stage(_state(missing_slots=["destination"]), hotel_options=[]),
            respond_module._derive_stage(_state(trip_data={"x": 1}), hotel_options=[{"id": "h1"}]),
            respond_module._derive_stage(_state(), hotel_options=[{"id": "h1"}]),
            respond_module._derive_stage(_state(), hotel_options=[]),
        }
        assert reachable == {"intake", "planned", "hotel_options"}


# `generate_next_chat_suggestions` swallows any exception from the LLM call
# and falls back to a hardcoded list (suggestions.py's `except Exception`),
# so a monkeypatch that *raises* can't distinguish "never called" from
# "called and failed" -- both leave the test green. A call counter can.
def _counting_llm(calls: list[int]):
    def _invoke(**_kwargs: Any) -> Any:
        calls.append(1)
        raise AssertionError("unreachable: only .invoke() should be called, not get_llm() again")

    return _invoke


# The exact hardcoded list `suggestions.py`'s `recommend_hotel*` short-circuit
# returns -- asserting equality (not just non-empty) is what actually
# distinguishes the short-circuit from the LLM-fallback list, which is
# different text.
_HOTEL_OPTIONS_HARDCODED_SUGGESTIONS = [
    "Chọn khách sạn số 1 và lập lịch trình",
    "Tìm thêm khách sạn gần biển hơn",
    "Lọc khách sạn có bể bơi và bao gồm ăn sáng",
]


class TestRespondSuggestions:
    def test_hotel_options_turn_gets_the_hardcoded_list_without_calling_the_llm(self, monkeypatch):
        calls: list[int] = []
        monkeypatch.setattr("src.services.suggestions.get_llm", _counting_llm(calls))
        monkeypatch.setattr(respond_module, "all_approved_amenities", lambda: ())

        response = respond(_state(task_results=_hotel_task_results()))["response"]

        assert response["stage"] == "hotel_options"
        assert [item["label"] for item in response["suggestions"]] == _HOTEL_OPTIONS_HARDCODED_SUGGESTIONS
        assert all(item["label"] == item["value"] for item in response["suggestions"])
        assert calls == []

    def test_intake_turn_skips_suggestions_entirely_without_calling_the_llm(self, monkeypatch):
        calls: list[int] = []
        monkeypatch.setattr("src.services.suggestions.get_llm", _counting_llm(calls))

        response = respond(_state(missing_slots=["destination"]))["response"]

        assert response["stage"] == "intake"
        assert response["suggestions"] == []
        assert calls == []

    def test_planned_turn_skips_suggestions_entirely_without_calling_the_llm(self, monkeypatch):
        # trip_data is sticky for the rest of the session (never reset by
        # load_context), so `planned` must never reach the LLM branch either
        # -- unlike hotel_options, it has no hardcoded list to fall back to.
        calls: list[int] = []
        monkeypatch.setattr("src.services.suggestions.get_llm", _counting_llm(calls))

        response = respond(_state(trip_data={"destination": "Đà Nẵng"}))["response"]

        assert response["stage"] == "planned"
        assert response["suggestions"] == []
        assert calls == []


class TestRespondCompoundPrice:
    def test_none_when_budget_slots_are_unset(self):
        response = respond(_state())["response"]
        assert response["compound_min_price"] is None
        assert response["compound_max_price"] is None

    def test_reflects_budget_min_and_max_slots(self):
        travel_state = _seeded(
            [
                {"path": "budget.min", "operation": "set", "value": 800_000},
                {"path": "budget.max", "operation": "set", "value": 2_500_000},
            ]
        )
        response = respond(_state(travel_state=travel_state.to_dict()))["response"]
        assert response["compound_min_price"] == 800_000
        assert response["compound_max_price"] == 2_500_000


class TestRespondActivePreferences:
    def test_empty_when_amenities_are_unset(self):
        response = respond(_state())["response"]
        assert response["active_preferences"] == []

    def test_reflects_hotel_preferences_amenities(self):
        travel_state = _seeded(
            [{"path": "hotel_preferences.amenities", "operation": "set", "value": ["gym", "pool"]}]
        )
        response = respond(_state(travel_state=travel_state.to_dict()))["response"]
        assert response["active_preferences"] == [
            {"id": "gym", "label": "gym"},
            {"id": "pool", "label": "pool"},
        ]


class _CatalogQuery:
    def __init__(self, rows: list[dict[str, Any]], calls: list[int]):
        self._rows = rows
        self._calls = calls

    def select(self, _fields: str) -> _CatalogQuery:
        return self

    def eq(self, _field: str, _value: Any) -> _CatalogQuery:
        return self

    def limit(self, _value: int) -> _CatalogQuery:
        return self

    def range(self, _start: int, _end: int) -> _CatalogQuery:
        return self

    def execute(self) -> SimpleNamespace:
        self._calls.append(1)
        return SimpleNamespace(data=self._rows)


class TestRespondAllPreferences:
    def test_catalog_is_not_queried_on_an_intake_stage_turn(self, monkeypatch):
        calls: list[int] = []

        class _Client:
            def table(self, _name: str) -> _CatalogQuery:
                return _CatalogQuery([], calls)

        monkeypatch.setattr(amenity_catalog_module, "get_supabase_client", lambda: _Client())
        amenity_catalog_module.clear_all_approved_amenities_cache()

        response = respond(_state(missing_slots=["destination"]))["response"]

        assert response["stage"] == "intake"
        assert response["all_preferences"] == []
        assert calls == []

    def test_catalog_is_queried_once_and_then_served_from_cache(self, monkeypatch):
        calls: list[int] = []
        rows = [
            {"id": "gym", "label_vi": "Gym", "scope": "hotel", "category": "facility", "match_keywords": ["gym"]}
        ]

        class _Client:
            def table(self, _name: str) -> _CatalogQuery:
                return _CatalogQuery(rows, calls)

        monkeypatch.setattr(amenity_catalog_module, "get_supabase_client", lambda: _Client())
        amenity_catalog_module.clear_all_approved_amenities_cache()
        try:
            first = respond(_state(task_results=_hotel_task_results()))["response"]
            second = respond(_state(task_results=_hotel_task_results()))["response"]

            assert first["all_preferences"] == [{"id": "gym", "label": "Gym"}]
            assert second["all_preferences"] == [{"id": "gym", "label": "Gym"}]
            assert len(calls) == 1
        finally:
            amenity_catalog_module.clear_all_approved_amenities_cache()


class TestRespondNeverSpeaksForASilentWorker:
    """The generic acknowledgement is the safety net, not the main road.

    A finished five-day itinerary used to arrive as "Đã cập nhật thông tin
    chuyến đi." because `itinerary_node`'s all-days-done path returned
    `task_results` untouched and `respond` found nothing to say.
    """

    def _built_trip(self) -> dict[str, Any]:
        return {
            "hotel": {"name": "Khách sạn Mường Thanh", "star_rating": 4},
            "itineraries": [
                {
                    "duration_days": 2,
                    "day_themes": [
                        {"day_number": 1, "title": "Khám phá trung tâm", "query": ""},
                        {"day_number": 2, "title": "Biển và hải sản", "query": ""},
                    ],
                }
            ],
            "itinerary_items": [
                {"day_number": 1, "start_time": "08:00:00", "activity": "Chợ Hàn", "order_index": 1},
                {"day_number": 2, "start_time": "09:00:00", "activity": "Bãi biển Mỹ Khê", "order_index": 1},
            ],
        }

    def _itinerary_task_results(self, trip_data: dict[str, Any]) -> list[dict[str, Any]]:
        # The entry itinerary_node's all-days-done path now appends.
        return [
            {
                "worker": "itinerary_node",
                "status": "ok",
                "reply": format_trip_summary_reply(trip_data, "vi"),
            }
        ]

    def test_a_finished_build_names_the_hotel_and_the_day_count(self):
        """Specific, not generic — but not the whole itinerary either. The UI
        renders the plan from `trip_plan`; the reply says what happened and
        points at it."""
        trip_data = self._built_trip()
        response = respond(
            _state(trip_data=trip_data, task_results=self._itinerary_task_results(trip_data))
        )["response"]

        assert response["reply"] != respond_module._ACK_VI
        assert "Khách sạn Mường Thanh" in response["reply"]
        assert "2 ngày" in response["reply"]
        assert response["stage"] == "planned"
        # The plan itself travels as structure, not as chat text.
        assert response["trip_plan"] is not None

    def test_the_reply_does_not_repeat_the_itinerary_the_ui_already_shows(self):
        trip_data = self._built_trip()
        reply = respond(
            _state(trip_data=trip_data, task_results=self._itinerary_task_results(trip_data))
        )["response"]["reply"]

        # No per-day activity dump: those live in day-timeline.tsx.
        assert "08:00" not in reply
        assert "Chợ Hàn" not in reply
        assert reply.count("\n") == 0

    def test_a_finished_build_never_names_internals_at_the_user(self):
        trip_data = self._built_trip()
        response = respond(
            _state(trip_data=trip_data, task_results=self._itinerary_task_results(trip_data))
        )["response"]

        for internal in ("itinerary_node:", "lock_days:", "edit_item:"):
            assert internal not in response["reply"]

    def test_falling_through_to_the_ack_is_logged_as_an_error(self, caplog):
        with caplog.at_level(logging.ERROR, logger=respond_module.__name__):
            response = respond(_state())["response"]

        assert response["reply"] == respond_module._ACK_VI
        assert any(
            "fell through to the generic ack" in record.getMessage() for record in caplog.records
        )


class TestTranscriptEcho:
    """Every reply goes back into `messages` tagged, and the tag is what the
    next turn reads to keep the same question out of two replies in a row.
    """

    @staticmethod
    def _sent(result: dict[str, Any]):
        return result["messages"][0]

    @staticmethod
    def _previous_reply(asked_slot: str | None) -> AIMessage:
        return AIMessage(
            content="Bạn dự định đi và về ngày nào?",
            additional_kwargs={"emitted_by": "respond", "asked_slot": asked_slot},
        )

    def test_the_reply_is_appended_tagged_with_the_slot_it_asked(self):
        result = respond(_state(missing_slots=["destination"], next_question="Bạn muốn đi đâu?"))

        sent = self._sent(result)
        assert sent.content == "Bạn muốn đi đâu?"
        assert sent.additional_kwargs == {"emitted_by": "respond", "asked_slot": "destination"}

    def test_a_worker_turn_records_no_asked_slot(self):
        result = respond(_state(task_results=[{"worker": "hotel_node", "status": "ok", "reply": "Có 3 khách sạn."}]))

        assert self._sent(result).additional_kwargs["asked_slot"] is None

    def test_an_answer_replaces_a_question_the_previous_reply_already_asked(self):
        result = respond(
            _state(
                messages=[self._previous_reply("dates.start")],
                missing_slots=["dates.start", "dates.end"],
                next_question="Bạn dự định đi và về ngày nào?",
                intake_answer="Tháng 7 Đà Nẵng có mưa rải rác.",
            )
        )

        assert result["response"]["reply"] == "Tháng 7 Đà Nẵng có mưa rải rác."
        # Dropped, so the next turn is free to ask it again.
        assert self._sent(result).additional_kwargs["asked_slot"] is None

    def test_the_question_returns_once_the_reply_above_it_carried_none(self):
        result = respond(
            _state(
                messages=[self._previous_reply(None)],
                missing_slots=["dates.start", "dates.end"],
                next_question="Bạn dự định đi và về ngày nào?",
                intake_answer="Tháng 7 Đà Nẵng có mưa rải rác.",
            )
        )

        reply = result["response"]["reply"]
        assert "mưa rải rác" in reply
        assert "đi và về" in reply
        assert self._sent(result).additional_kwargs["asked_slot"] == "dates.start"

    def test_a_failed_answer_still_gets_re_asked(self):
        """The plain "ask" branch has no answer to send in the question's
        place — dropping it there would leave the intake with nothing on
        screen to move it forward."""
        result = respond(
            _state(
                messages=[self._previous_reply("dates.start")],
                missing_slots=["dates.start", "dates.end"],
                next_question="Bạn dự định đi và về ngày nào?",
            )
        )

        assert result["response"]["reply"] == "Bạn dự định đi và về ngày nào?"
        assert self._sent(result).additional_kwargs["asked_slot"] == "dates.start"

    def test_a_qa_node_message_is_never_mistaken_for_a_previous_question(self):
        result = respond(
            _state(
                messages=[AIMessage(content="Phòng đó còn trống.")],
                missing_slots=["destination"],
                next_question="Bạn muốn đi đâu?",
                intake_answer="Huế có Đại Nội và chùa Thiên Mụ.",
            )
        )

        assert "Bạn muốn đi đâu?" in result["response"]["reply"]

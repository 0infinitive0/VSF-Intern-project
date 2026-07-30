from __future__ import annotations

import json

import pytest

from src.services.trip_edit_planner import TripEditPlanError, parse_trip_edit_plan, plan_trip_edit


def _trip_data() -> dict:
    return {
        "hotel": {
            "id": "hotel-1",
            "name": "Hotel One",
            "destination_id": "destination-1",
            "coordinates": "10.7,106.7",
            "covered_meals": [],
        },
        "itineraries": [
            {
                "id": "itinerary-1",
                "duration_days": 2,
                "day_themes": [
                    {"day_number": 1, "title": "Văn hóa", "query": "museum"},
                    {"day_number": 2, "title": "Thiên nhiên", "query": "park"},
                ],
            }
        ],
        "itinerary_items": [
            {
                "id": "breakfast-1",
                "day_number": 1,
                "order_index": 1,
                "item_kind": "breakfast",
                "reference_id": "old-breakfast",
                "activity": "Ăn sáng tại Quán Cũ",
                "start_time": "07:00:00",
                "end_time": "08:00:00",
            }
        ],
    }


def test_replace_breakfast_requires_a_real_current_item_id() -> None:
    payload = {
        "decision": "apply",
        "summary": "Đổi bữa sáng ngày 1",
        "confidence": 0.95,
        "operations": [
            {
                "operation": "replace_item",
                "target": {"item_id": "breakfast-1", "day_number": 1, "item_kind": "breakfast"},
                "requirements": {
                    "item_kind": "breakfast",
                    "semantic_query": "địa điểm ăn sáng",
                    "near": "hotel",
                    "preserve_start_time": True,
                    "preserve_duration": True,
                    "real_place_required": True,
                },
            }
        ],
    }

    plan = parse_trip_edit_plan(payload, _trip_data())

    operation = plan.operations[0]
    assert operation.operation == "replace_item"
    assert operation.target and operation.target.item_id == "breakfast-1"
    assert operation.requirements and operation.requirements.item_kind == "breakfast"


def test_hallucinated_item_id_is_rejected_before_execution() -> None:
    payload = {
        "decision": "apply",
        "summary": "Đổi bữa sáng",
        "operations": [
            {
                "operation": "replace_item",
                "target": {"item_id": "made-up-item"},
                "requirements": {"item_kind": "breakfast", "semantic_query": "breakfast"},
            }
        ],
    }

    with pytest.raises(TripEditPlanError, match="item_id"):
        parse_trip_edit_plan(payload, _trip_data())


def test_flat_item_id_from_the_configured_model_is_normalized_to_target() -> None:
    payload = {
        "decision": "apply",
        "summary": "Đổi bữa sáng",
        "operations": [
            {
                "operation": "replace_item",
                "item_id": "breakfast-1",
                "requirements": {"item_kind": "breakfast", "semantic_query": "địa điểm ăn sáng"},
            }
        ],
    }

    plan = parse_trip_edit_plan(payload, _trip_data())

    assert plan.operations[0].target and plan.operations[0].target.item_id == "breakfast-1"


def test_planner_retries_once_after_malformed_llm_json() -> None:
    class FakeLlm:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, _prompt: str):
            self.calls += 1
            content = "not json" if self.calls == 1 else json.dumps({"decision": "not_edit", "summary": "question"})
            return type("Response", (), {"content": content})()

    llm = FakeLlm()

    plan = plan_trip_edit("câu hỏi chung", _trip_data(), llm=llm)

    assert plan.decision == "not_edit"
    assert llm.calls == 2

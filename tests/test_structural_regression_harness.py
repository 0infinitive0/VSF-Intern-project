"""Structural regression harness for Phase 2's services/agents/cli re-layer.

`create_react_agent`'s underlying LLM samples non-deterministically with no
seed, so a captured-transcript text diff is unsound: it is either permanently
red from harmless wording drift, or it hides a real regression as "LLM noise".
This harness asserts on STRUCTURE instead — which tool ran, in what order, with
what arguments; the shape of trip_data / pending_hotel_selection; the
`SYSTEM ERROR:` prefix; and `suggestions_for()` output — for one scripted
session: intake -> hotel prefs -> hotel list -> pick 1 -> edit day 2 ->
finalize.

Every step of Phase 2 re-runs `test_full_session_structural_signature` and
diffs the recorded signature against `EXPECTED_SIGNATURE` below. The LLM
itself is fully stubbed (module-level monkeypatches on src.agents.session, plus
a fake SessionTools bundle so tool.invoke() never reaches a live tool) so the
run is deterministic and CI-safe — no live Ollama/Supabase calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import src.agents.session as session_module
from src.agents.session import create_chat_session, process_chat_turn, suggestions_for
from src.services.trip_edit_planner import TripEditPlan


def _fake_hotel_options() -> list[dict]:
    return [
        {
            "id": "hotel-1",
            "name": "Muong Thanh Grand",
            "star_rating": 4,
            "description": "Central beachfront hotel",
            "matched_rooms": ["Deluxe"],
            "rank": 1,
        },
        {
            "id": "hotel-2",
            "name": "Vinpearl Resort",
            "star_rating": 5,
            "description": "Resort with private beach",
            "matched_rooms": ["Suite"],
            "rank": 2,
        },
    ]


def _fake_trip_data(destination: str = "Đà Nẵng", hotel_id: str = "hotel-1") -> dict:
    return {
        "hotel": {"id": hotel_id, "name": "Muong Thanh Grand", "star_rating": 4},
        "itineraries": [
            {
                "id": "itinerary-1",
                "session_id": "harness-session",
                "destination_id": "dest-1",
                "duration_days": 3,
                "number_of_adults": 2,
                "preferences": [destination],
                "day_themes": [
                    {"day_number": 1, "title": "Beach day", "query": "beach"},
                    {"day_number": 2, "title": "City exploration", "query": "city"},
                    {"day_number": 3, "title": "Culture", "query": "culture"},
                ],
                "status": "Draft",
            }
        ],
        "itinerary_items": [
            {
                "id": "item-1",
                "day_number": 1,
                "order_index": 1,
                "start_time": "08:00:00",
                "end_time": "09:00:00",
                "activity": "Ăn sáng",
                "kind": "breakfast",
                "reference_type": "Attraction",
                "reference_id": "attr-1",
            },
            {
                "id": "item-2",
                "day_number": 2,
                "order_index": 1,
                "start_time": "09:00:00",
                "end_time": "11:00:00",
                "activity": "Tham quan bảo tàng",
                "kind": "attraction",
                "reference_type": "Attraction",
                "reference_id": "attr-2",
            },
        ],
        "adjustments": [],
    }


class _FakeTool:
    def __init__(self, invoke_fn):
        self._invoke_fn = invoke_fn

    def invoke(self, args):
        return self._invoke_fn(args)


class _FakeTools:
    """Stands in for the session's SessionTools bundle so process_chat_turn's
    `session.tools.<name>.invoke(...)` calls never reach a live tool."""

    def __init__(self, session, calls: list[tuple[str, dict]]):
        self._session = session
        self._calls = calls
        self.recommend_hotels = _FakeTool(self._recommend_hotels)
        self.select_hotel = _FakeTool(self._select_hotel)
        self.finalize_trip_plan = _FakeTool(self._finalize_trip_plan)
        self.modify_trip_plan = _FakeTool(lambda args: "not used by this script")

    def _recommend_hotels(self, args):
        self._calls.append(("recommend_hotels", dict(args)))
        self._session.pending_hotel_selection = {
            "mode": "new_trip",
            "destination": args.get("destination"),
            "duration": args.get("duration"),
            "people": args.get("people"),
            "preferences_text": args.get("preferences", ""),
            "options": _fake_hotel_options(),
        }
        return "here are 2 hotels"

    def _select_hotel(self, args):
        self._calls.append(("select_hotel", dict(args)))
        selection = str(args.get("selection", "")).strip()
        if selection not in {"1", "2"}:
            return "SYSTEM ERROR: could not resolve the hotel choice"
        hotel_id = "hotel-1" if selection == "1" else "hotel-2"
        self._session.trip_data = _fake_trip_data(hotel_id=hotel_id)
        self._session.pending_hotel_selection = None
        return "Hotel: Muong Thanh Grand"

    def _finalize_trip_plan(self, _args):
        self._calls.append(("finalize_trip_plan", {}))
        self._session.trip_data["itineraries"][0]["status"] = "Finalized"
        return "Đã xác nhận lịch trình và lưu làm mẫu có thể tái sử dụng."


def _install_stubs(monkeypatch, session, calls: list[tuple[str, dict]]) -> None:
    """Stub every module-level symbol process_chat_turn dispatches to, recording
    (tool_name, args) into `calls` in invocation order — the "which tool ran, in
    what order, with what arguments" half of the structural signature."""

    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Đà Nẵng",))

    def _fake_intake_extraction(message, known_facts, destination_names, model=None):
        responses = {
            "Tôi muốn đi Đà Nẵng": {"destination": "Đà Nẵng"},
            "3 ngày": {"duration_days": 3},
            "2 người": {"people_count": 2},
        }
        return responses.get(message, {})

    monkeypatch.setattr(
        "src.services.trip_intake._llm_extract_intake_facts", _fake_intake_extraction
    )

    session.tools = _FakeTools(session, calls)

    def _fake_plan_trip_edit(request, current_data):
        return TripEditPlan(decision="apply", summary="Edit day 2", raw_request=request)

    monkeypatch.setattr(session_module, "plan_trip_edit", _fake_plan_trip_edit)

    def _fake_execute_trip_edit_request(_session, user_input, plan):
        calls.append(("execute_trip_edit_request", {"user_input": user_input, "decision": plan.decision}))
        session.trip_data["adjustments"].append("Đã đổi hoạt động ngày 2.")
        return "Đã cập nhật lịch trình ngày 2."

    monkeypatch.setattr(session_module, "execute_trip_edit_request", _fake_execute_trip_edit_request)
    monkeypatch.setattr(
        "src.agents.routing_decision.is_finalization_request",
        lambda text: "chốt" in text.casefold(),
    )


def _capture_signature(session, calls: list[tuple[str, dict]]) -> dict:
    trip_data = session.trip_data
    itinerary = (trip_data or {}).get("itineraries", [{}])[0]
    return {
        "tool_calls": calls,
        "trip_data_shape": {
            "day_count": itinerary.get("duration_days"),
            "item_count": len(trip_data.get("itinerary_items", [])) if trip_data else 0,
            "hotel_id": (trip_data or {}).get("hotel", {}).get("id"),
            "status": itinerary.get("status"),
        },
        "pending_hotel_selection": session.pending_hotel_selection,
        "suggestions": suggestions_for(session),
    }


EXPECTED_SIGNATURE = {
    "tool_calls": [
        (
            "recommend_hotels",
            {
                "destination": "Đà Nẵng",
                "duration": "3 ngày",
                "people": "2 người",
                "preferences": "",
                "target_price": "",
                "min_price": "",
                "max_price": "",
            },
        ),
        ("select_hotel", {"selection": "1"}),
        (
            "execute_trip_edit_request",
            {"user_input": "đổi hoạt động ngày 2 sang buổi chiều", "decision": "apply"},
        ),
        ("finalize_trip_plan", {}),
    ],
    "trip_data_shape": {
        "day_count": 3,
        "item_count": 2,
        "hotel_id": "hotel-1",
        "status": "Finalized",
    },
    "pending_hotel_selection": None,
    "suggestions": [],
}


@pytest.fixture(autouse=True)
def _no_llm_construction(monkeypatch):
    """create_chat_session builds a real compiled agent (get_llm + create_react_agent)
    that this harness immediately overwrites with _FakeTools — avoid touching a real
    provider during that brief window by stubbing get_llm's constructor path."""
    monkeypatch.setattr(session_module, "build_trip_agent", lambda session, **_kwargs: (object(), None))


def test_full_session_structural_signature(monkeypatch):
    """Script: intake -> hotel prefs -> hotel list -> pick 1 -> edit day 2 -> finalize.

    Re-run after every Phase 2 step; the captured signature must stay byte-for-byte
    equal to EXPECTED_SIGNATURE (recorded here at step 3, pre-move).
    """
    calls: list[tuple[str, dict]] = []
    session = create_chat_session("harness-session")
    _install_stubs(monkeypatch, session, calls)

    reply = process_chat_turn(session, "Tôi muốn đi Đà Nẵng")
    assert not reply.text.startswith("SYSTEM ERROR:")

    reply = process_chat_turn(session, "3 ngày")
    assert not reply.text.startswith("SYSTEM ERROR:")

    reply = process_chat_turn(session, "2 người")
    assert not reply.text.startswith("SYSTEM ERROR:")
    # Trip facts complete -> guided hotel-budget question, no tool call yet.
    assert session.intake_state.is_complete

    reply = process_chat_turn(session, "bao nhiêu cũng được")
    assert not reply.text.startswith("SYSTEM ERROR:")
    assert session.hotel_pref_state.is_complete
    assert calls and calls[-1][0] == "recommend_hotels"

    reply = process_chat_turn(session, "1")
    assert not reply.text.startswith("SYSTEM ERROR:")
    assert session.initial_plan_complete is True
    assert calls[-1][0] == "select_hotel"

    reply = process_chat_turn(session, "đổi hoạt động ngày 2 sang buổi chiều")
    assert not reply.text.startswith("SYSTEM ERROR:")
    assert calls[-1][0] == "execute_trip_edit_request"

    reply = process_chat_turn(session, "chốt lịch trình")
    assert not reply.text.startswith("SYSTEM ERROR:")
    assert calls[-1][0] == "finalize_trip_plan"

    signature = _capture_signature(session, calls)
    assert signature == EXPECTED_SIGNATURE


def test_create_react_agent_has_exactly_two_owners_in_src():
    """Phase 1 deleted the CLI fork's own create_react_agent + MemorySaver
    (src/cli/planner_tools.py:678) and the dead template graph
    (src/agents/graph.py's old `agent`). A third call site reappearing means a
    parallel agent-construction path has crept back in."""
    src_root = Path(__file__).resolve().parents[1] / "src"
    owners = sorted(
        str(path.relative_to(src_root))
        for path in src_root.rglob("*.py")
        if "create_react_agent(" in path.read_text(encoding="utf-8")
    )
    assert owners == ["agents/graph.py", "agents/supervisor.py"]

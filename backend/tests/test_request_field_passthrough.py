"""Request fields that were validated and then dropped on the floor.

`_run_turn_via_graph` takes `(session_id, message, language, extra_state)`.
Anything else a request model declared was parsed, type-checked, and silently
discarded — a contract that looks honest from the outside and does nothing.
Two shapes of that bug are covered here:

- `selection_message`: the client sends the label the user actually saw, the
  route overwrote it with a machine-made string.
- `stay_dates`/`min_price`/`max_price`: declared and validated on
  `PlannerChatRequest`, never forwarded, never sent by any client. Deleted
  rather than wired — routing them into `travel_state` would open a path around
  `extract_patch -> validate_patch -> apply_patch`, which is the pipeline the
  whole state design exists to funnel writes through.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import src.api.routes as routes
from src.models import schemas


class _RecordingGraphApp:
    """Captures the message each turn is started with."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.extra_state: list[dict[str, Any]] = []

    def get_state(self, _config):
        return SimpleNamespace(values={}, interrupts=())

    def invoke(self, payload, config=None):
        if isinstance(payload, dict):
            self.messages.append(str(payload["messages"][0].content))
            self.extra_state.append({k: v for k, v in payload.items() if k not in {"messages"}})
        return {"response": {"session_id": "s1", "reply": "ok", "stage": "intake"}}


@pytest.fixture
def recorded_turn(monkeypatch: pytest.MonkeyPatch) -> _RecordingGraphApp:
    app = _RecordingGraphApp()
    monkeypatch.setattr(routes, "_get_graph_v2", lambda: app)
    monkeypatch.setattr(routes, "_persistence_enabled", False)
    monkeypatch.setattr(
        routes.registry,
        "get",
        lambda _sid: SimpleNamespace(
            session_id="s1", owner_user_id=None, language="vi", lock=_NullLock()
        ),
    )
    monkeypatch.setattr(routes.registry, "evict_expired", lambda: None)
    return app


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


_SESSION_ID = "00000000-0000-4000-8000-000000000001"


class TestSelectionMessage:
    def test_the_clients_own_wording_becomes_the_turn_message(self, recorded_turn):
        """The transcript should read the way the user's screen did. The route
        used to substitute "Tôi chọn khách sạn ID <uuid>", so the saved
        conversation showed an id the user never saw."""
        routes.select_hotel(
            schemas.SelectHotelRequest(
                session_id=_SESSION_ID,
                hotel_id="h-1",
                selection_message="Chọn khách sạn Mường Thanh",
            ),
            None,
        )

        assert recorded_turn.messages == ["Chọn khách sạn Mường Thanh"]

    def test_an_older_client_that_sends_no_message_still_works(self, recorded_turn):
        routes.select_hotel(
            schemas.SelectHotelRequest(session_id=_SESSION_ID, hotel_id="h-1"), None
        )

        assert recorded_turn.messages == ["Tôi chọn khách sạn ID h-1"]

    def test_the_deterministic_signal_is_unchanged(self, recorded_turn):
        """`selected_hotel_id` is what `hotel_node` acts on; the message is only
        transcript. Changing the text must not change the behavior."""
        routes.select_hotel(
            schemas.SelectHotelRequest(
                session_id=_SESSION_ID, hotel_id="h-9", selection_message="bất kỳ"
            ),
            None,
        )

        assert recorded_turn.extra_state[0]["selected_hotel_id"] == "h-9"


class TestPlannerChatRequestSurface:
    def test_a_message_is_required(self):
        """What the old `model_validator` was expressing in a roundabout way:
        a turn with no message is not a turn."""
        with pytest.raises(ValidationError):
            schemas.PlannerChatRequest(session_id=_SESSION_ID)

    def test_an_empty_message_is_rejected(self):
        with pytest.raises(ValidationError):
            schemas.PlannerChatRequest(session_id=_SESSION_ID, message="")

    def test_the_dropped_fields_are_gone_from_the_model(self):
        """Not merely unused — absent, so `/openapi.json` stops advertising
        inputs the server ignores (Phase 8 generates the client types from it)."""
        fields = set(schemas.PlannerChatRequest.model_fields)
        assert fields == {"session_id", "message", "language"}

    def test_every_declared_field_reaches_the_graph(self, recorded_turn):
        request = schemas.PlannerChatRequest(
            session_id=_SESSION_ID, message="đi đà nẵng", language="en"
        )

        routes.planner_chat(request, None)

        assert recorded_turn.messages == ["đi đà nẵng"]
        assert recorded_turn.extra_state[0]["language"] == "en"


def test_select_place_request_is_gone():
    """A model with no route. `qa_node`'s docstring records the intended design
    as interrupt-resume inside `rebuild_day`, not a `select_place` endpoint."""
    assert not hasattr(schemas, "SelectPlaceRequest")

from __future__ import annotations

import src.agents.session as session_module
import src.cli.terminal_chat as terminal_chat_module


def test_run_terminal_chat_starts_with_no_pending_hotel_selection(monkeypatch):
    """A fresh TripSession always starts with pending_hotel_selection=None — state
    is per-session now, so there is no longer a global file a previous run/crash
    could leave stale to poison the first message of a new session."""
    captured = {}

    real_create_chat_session = session_module.create_chat_session

    def _capturing_create_chat_session(session_id, **kwargs):
        session = real_create_chat_session(session_id, **kwargs)
        captured["session"] = session
        return session

    monkeypatch.setattr(terminal_chat_module, "create_chat_session", _capturing_create_chat_session)
    monkeypatch.setattr(session_module, "build_trip_agent", lambda session, **_kwargs: (object(), object()))
    # Immediately quit — we only care about state at the moment the loop starts.
    monkeypatch.setattr("builtins.input", lambda _prompt="": "quit")

    terminal_chat_module.run_terminal_chat()

    assert captured["session"].pending_hotel_selection is None
    assert captured["session"].trip_data is None

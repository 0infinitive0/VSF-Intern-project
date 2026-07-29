from __future__ import annotations

import os

import pytest

import src.cli.terminal_chat as terminal_chat_module
import src.services.chat_session as chat_session_module
from src.cli.trip_builder_svc import PENDING_HOTEL_SELECTION_FILE


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_run_terminal_chat_clears_stale_pending_selection_file_on_start(monkeypatch):
    """A pending_hotel_selection.json left over from a previous run/crash must not
    make the first message of a new session get misread as a hotel choice reply."""
    with open(PENDING_HOTEL_SELECTION_FILE, "w", encoding="utf-8") as file_handle:
        file_handle.write('{"mode": "new_trip", "options": []}')
    assert os.path.exists(PENDING_HOTEL_SELECTION_FILE)

    monkeypatch.setattr(chat_session_module, "create_planner_agent", lambda: object())
    # Immediately quit — we only care about state at the moment the loop starts.
    monkeypatch.setattr("builtins.input", lambda _prompt="": "quit")

    terminal_chat_module.run_terminal_chat()

    assert not os.path.exists(PENDING_HOTEL_SELECTION_FILE)

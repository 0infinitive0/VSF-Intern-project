"""Terminal Interactive Chat interface for the Trip Planner."""

from __future__ import annotations

import logging

from src.cli.trip_builder_svc import _clear_pending_hotel_selection
from src.services.chat_session import create_chat_session, process_chat_turn

logger = logging.getLogger(__name__)


def run_terminal_chat():
    """Main interactive terminal loop for the Trip Planner."""
    print("==================================================")
    print("Welcome to the Trip Planner CLI (Powered by Llama3)")
    print("Type 'quit' or 'exit' to stop.")
    print("==================================================\n")

    # A pending_hotel_selection.json left over from a previous run that exited/crashed
    # mid-flow would otherwise make the very first message of this new session get
    # misread as a hotel choice reply — this is process-lifetime state, just like the
    # ChatSession created below, so it starts fresh every run.
    _clear_pending_hotel_selection()

    session = create_chat_session("poc_trip_planner_1")

    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ["quit", "exit"]:
                break

            if not user_input.strip():
                continue

            print("\nAgent is thinking...\n")
            reply = process_chat_turn(session, user_input)
            print(f"\nAI:\n{reply}")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break
        except Exception as e:
            print(f"\nAn error occurred: {e}")


if __name__ == "__main__":
    run_terminal_chat()

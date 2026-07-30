"""Terminal Interactive Chat interface for the Trip Planner."""

from __future__ import annotations

import logging
import os

from src.cli.trip_builder_svc import (
    CURRENT_TRIP_PLAN_FILE,
    PENDING_HOTEL_SELECTION_FILE,
    _clear_pending_hotel_selection,
    clear_session_history,
)
from src.config import get_settings
from src.services.chat_session import create_chat_session, process_chat_turn
from src.services.suggestions import generate_next_chat_suggestions

logger = logging.getLogger(__name__)


def _print_suggestions(context_text: str, last_action: str) -> None:
    try:
        suggestions = generate_next_chat_suggestions(context_text, last_action=last_action)
        if suggestions:
            print("\n💡 Gợi ý câu hỏi tiếp theo:")
            for index, suggestion in enumerate(suggestions, 1):
                print(f'   {index}. "{suggestion}"')
    except Exception as exc:
        logger.debug("Could not print suggestions: %s", exc)


def _suggestion_action(reply: str, had_pending_hotel_selection: bool) -> str | None:
    if had_pending_hotel_selection:
        return "hotel_selected"
    if os.path.exists(PENDING_HOTEL_SELECTION_FILE):
        return "recommend_hotels"
    if "đã xác nhận lịch trình" in reply.casefold():
        return "finalized"
    if os.path.exists(CURRENT_TRIP_PLAN_FILE):
        return "general"
    return None


def run_terminal_chat() -> None:
    """Run the terminal transport over the shared chat-session state machine."""
    settings = get_settings()
    model_name = os.environ.get("LLM_MODEL") or settings.llm_model or "llama3.1"

    print("==================================================")
    print(f"Welcome to the Trip Planner CLI (Powered by {model_name})")
    print("Type 'quit' or 'exit' to stop. Type '/clear' to reset chat history.")
    print("==================================================\n")

    # A previous crash can leave the next message looking like a hotel choice.
    # Keep the saved itinerary, but reset this process-lifetime selection state.
    _clear_pending_hotel_selection()
    session = create_chat_session("poc_trip_planner_1")

    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.casefold() in {"quit", "exit"}:
                break
            if not user_input.strip():
                continue

            if user_input.casefold() in {"/clear", "clear", "reset"}:
                clear_session_history()
                session = create_chat_session("poc_trip_planner_1")
                print("\n🧹 Session and chat history cleared! Started a fresh chat.\n")
                continue

            had_pending_hotel_selection = os.path.exists(PENDING_HOTEL_SELECTION_FILE)
            print("\nAgent is thinking...\n")
            reply = str(process_chat_turn(session, user_input))
            print(f"\nAI:\n{reply}")

            if not reply.startswith("SYSTEM ERROR:"):
                action = _suggestion_action(reply, had_pending_hotel_selection)
                if action:
                    _print_suggestions(reply, action)

        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break
        except Exception as exc:
            print(f"\nAn error occurred: {exc}")


if __name__ == "__main__":
    run_terminal_chat()

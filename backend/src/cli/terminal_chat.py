"""Terminal Interactive Chat interface for the Trip Planner."""

from __future__ import annotations

import logging
import os

from src.agents.session import (
    clear_session_history,
    cli_persist_hook,
    create_chat_session,
    process_chat_turn,
)
from src.config import get_settings
from src.services.suggestions import SuggestionContext, SuggestionHotelCard, generate_next_chat_suggestions

logger = logging.getLogger(__name__)

_CLI_SESSION_ID = "poc_trip_planner_1"


def _print_suggestions(context: SuggestionContext) -> None:
    try:
        suggestions = generate_next_chat_suggestions(context)
        if suggestions:
            print("\n💡 Gợi ý câu hỏi tiếp theo:")
            for index, suggestion in enumerate(suggestions, 1):
                print(f'   {index}. "{suggestion}"')
    except Exception as exc:
        logger.debug("Could not print suggestions: %s", exc)


def _cli_suggestion_context(session, reply: str, had_pending_hotel_selection: bool) -> SuggestionContext | None:
    """Best-effort `SuggestionContext` from the CLI's legacy `TripSession`.

    The CLI runs the pre-graph_v2 plane (`src.agents.session`), a
    structurally different session type from the web path's
    `TravelGraphState` -- no `task_results`, so there is no worker/status
    signal to gate on here the way `routes.py` does. This infers an
    equivalent "what did this turn just do" label from the same session
    fields the old `_suggestion_action` read, kept only so the CLI and web
    call the same `generate_next_chat_suggestions(context)` API -- grounding
    detail (amenity labels, active filters) is intentionally thinner here,
    the CLI is a dev tool, not the shipped surface this plan is fixing.
    """
    if had_pending_hotel_selection or session.pending_hotel_selection is not None:
        worker = "hotel_node"
    elif "đã xác nhận lịch trình" in reply.casefold():
        worker = "booking_node"
    elif session.trip_data is not None:
        worker = "itinerary_node"
    else:
        return None

    pending = session.pending_hotel_selection or {}
    hotel_cards = tuple(
        SuggestionHotelCard(
            name=str(option.get("name") or ""),
            price=option.get("average_nightly_price"),
            review_score=option.get("review_score"),
        )
        for option in pending.get("options") or []
        if isinstance(option, dict) and option.get("name")
    )

    return SuggestionContext(
        worker=worker,
        status="ok",
        reply=reply,
        language=session.language,
        hotel_cards=hotel_cards,
    )


def run_terminal_chat() -> None:
    """Run the terminal transport over the shared chat-session state machine."""
    settings = get_settings()
    model_name = os.environ.get("LLM_MODEL") or settings.llm_model or "llama3.1"

    print("==================================================")
    print(f"Welcome to the Trip Planner CLI (Powered by {model_name})")
    print("Type 'quit' or 'exit' to stop. Type '/clear' to reset chat history.")
    print("==================================================\n")

    # A previous crash can leave the session looking like a hotel choice is
    # pending. A fresh TripSession starts clean, so no explicit clear is needed
    # here the way the old global-file version required one.
    session = create_chat_session(_CLI_SESSION_ID, persist_hook=cli_persist_hook)

    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.casefold() in {"quit", "exit"}:
                break
            if not user_input.strip():
                continue

            if user_input.casefold() in {"/clear", "clear", "reset"}:
                clear_session_history(session)
                session = create_chat_session(_CLI_SESSION_ID, persist_hook=cli_persist_hook)
                print("\n🧹 Session and chat history cleared! Started a fresh chat.\n")
                continue

            had_pending_hotel_selection = session.pending_hotel_selection is not None
            print("\nAgent is thinking...\n")
            reply = process_chat_turn(session, user_input).text
            print(f"\nAI:\n{reply}")

            if not reply.startswith("SYSTEM ERROR:"):
                context = _cli_suggestion_context(session, reply, had_pending_hotel_selection)
                if context:
                    _print_suggestions(context)

        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break
        except Exception as exc:
            print(f"\nAn error occurred: {exc}")


if __name__ == "__main__":
    run_terminal_chat()

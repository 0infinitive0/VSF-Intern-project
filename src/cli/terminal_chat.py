"""Terminal Interactive Chat interface for the Trip Planner."""

from __future__ import annotations

import logging
import os
import sys

from src.cli.planner_tools import (
    _is_finalization_request,
    create_planner_agent,
    finalize_trip_plan,
    recommend_hotels,
    select_hotel,
)
from src.cli.trip_builder_svc import (
    CURRENT_TRIP_PLAN_FILE,
    PENDING_HOTEL_SELECTION_FILE,
    _get_destination_names,
)
from src.services.trip_intake import TripIntakeState
from src.services.trip_scheduler import infer_trip_change

logger = logging.getLogger(__name__)


def run_terminal_chat():
    """Main interactive terminal loop for the Trip Planner."""
    print("==================================================")
    print("Welcome to the Trip Planner CLI (Powered by Llama3)")
    print("Type 'quit' or 'exit' to stop.")
    print("==================================================\n")

    agent = create_planner_agent()
    config = {"configurable": {"thread_id": "poc_trip_planner_1"}}
    intake_state = TripIntakeState()
    initial_plan_complete = False

    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ["quit", "exit"]:
                break

            if not user_input.strip():
                continue

            logger.info(f"User Input: {user_input}")

            if os.path.exists(PENDING_HOTEL_SELECTION_FILE):
                tool_response = select_hotel.invoke({"selection": user_input})
                logger.info("Hotel selection response: %s", tool_response)
                print(f"\nAI:\n{tool_response}")
                initial_plan_complete = not str(tool_response).startswith("SYSTEM ERROR:")
                continue

            if os.path.exists(CURRENT_TRIP_PLAN_FILE) and _is_finalization_request(user_input):
                tool_response = finalize_trip_plan.invoke({})
                logger.info("Finalization response: %s", tool_response)
                print(f"\nAI:\n{tool_response}")
                initial_plan_complete = not str(tool_response).startswith("SYSTEM ERROR:")
                continue

            change_intent = infer_trip_change(user_input)
            is_saved_plan_edit = bool(
                os.path.exists(CURRENT_TRIP_PLAN_FILE) and change_intent is not None
            )
            if not initial_plan_complete and not is_saved_plan_edit:
                intake_state = intake_state.with_message(user_input, _get_destination_names())
                missing_question = intake_state.next_question()
                if missing_question:
                    logger.info("Deterministic intake response: %s", missing_question)
                    print(f"\nAI:\n{missing_question}")
                    continue

                print("\nAgent is building the verified trip plan...\n")
                verified_arguments = intake_state.tool_arguments()
                logger.info("Deterministic intake complete: %s", verified_arguments)
                tool_response = recommend_hotels.invoke(verified_arguments)
                logger.info("Final Tool Response Output:\n%s", tool_response)
                print(f"\nAI:\n{tool_response}")
                continue

            print("\nAgent is thinking...\n")

            # Stream the response to show agent flow
            events = agent.stream(
                {"messages": [("user", user_input)]},
                config=config,
                stream_mode="values",
            )

            final_ai_response = None
            tool_output_response = None
            for event in events:
                if "messages" in event:
                    latest_message = event["messages"][-1]

                    # Print agent flow debugging info
                    if latest_message.type == "ai" and latest_message.tool_calls:
                        tool_names = ", ".join([tc["name"] for tc in latest_message.tool_calls])
                        print(f"🔄 [Agent Flow: Supervisor is delegating to {tool_names}...]")
                        logger.info(f"Delegating to tools: {tool_names}")

                    elif latest_message.type == "tool":
                        if "SYSTEM ERROR:" not in str(latest_message.content):
                            print(f"✅ [Agent Flow: {latest_message.name} returned results]")
                            tool_output_response = latest_message.content
                        logger.info(f"Tool returned: {latest_message.name}")

                    if latest_message.type == "ai" and not latest_message.tool_calls:
                        final_ai_response = latest_message.content

            # Print the final AI response after the loop finishes
            if tool_output_response:
                logger.info(f"Final Tool Response Output:\n{tool_output_response}")
                print(f"\nAI:\n{tool_output_response}")
            elif final_ai_response:
                logger.info(f"Final AI Response: {final_ai_response}")
                print(f"\nAI:\n{final_ai_response}")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break
        except Exception as e:
            print(f"\nAn error occurred: {e}")


if __name__ == "__main__":
    run_terminal_chat()

"""Entry point runner for the interactive terminal trip planner CLI.

This script delegates core logic to modular services under `src.cli`.
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.cli.planner_tools import (
    SUPERVISOR_PROMPT,
    create_planner_agent,
    finalize_trip_plan,
    generate_full_itinerary,
    modify_trip_plan,
    recommend_hotels,
    select_hotel,
)
from src.cli.terminal_chat import run_terminal_chat
from src.services.hotel_selection import select_hotel_candidates
from src.cli.trip_builder_svc import (
    CURRENT_TRIP_PLAN_FILE,
    PENDING_HOTEL_SELECTION_FILE,
    _apply_local_trip_change,
    _build_trip_data,
    _current_trip_parameters,
    _find_reusable_template,
    _generate_day_themes,
    _get_destination_id,
    _get_destination_names,
    _hydrate_records,
    _item_kind,
    _parse_trip_change,
    _persist_itinerary_metadata,
    _replace_day_in_json,
    _save_trip_data,
    _scheduled_day_from_json,
    _search_attraction_candidates,
    _select_real_hotel,
    _serialize_schedule_item,
    _strip_json_fence,
    _to_place_candidates,
    build_natural_activity_string,
    format_hotel_options,
    format_trip_response_from_json,
    parse_duration_to_days,
)


def main():
    """Run the interactive terminal chat CLI."""
    run_terminal_chat()


if __name__ == "__main__":
    main()

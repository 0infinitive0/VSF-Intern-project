"""Terminal Chat CLI module.

Deliberately does NOT import `src.cli.terminal_chat` here: that module now
depends on `src.services.chat_session`, which itself imports from
`src.cli.planner_tools` — importing `terminal_chat` at package-init time would
re-enter this same `__init__.py` before it finished, a circular import.
Nothing in the codebase imports `run_terminal_chat` via `from src.cli import
...` anyway (always the fully-qualified `src.cli.terminal_chat`), so it isn't
re-exported here.
"""

from src.cli.planner_tools import (
    create_planner_agent,
    finalize_trip_plan,
    generate_full_itinerary,
    modify_trip_plan,
    recommend_hotels,
    select_hotel,
)

__all__ = [
    "create_planner_agent",
    "recommend_hotels",
    "select_hotel",
    "generate_full_itinerary",
    "modify_trip_plan",
    "finalize_trip_plan",
]

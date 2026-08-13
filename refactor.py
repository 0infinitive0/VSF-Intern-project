import re

with open("backend/src/agents/session.py", "r") as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    # Keep up to 397 and from 1521
    if i < 397 or i >= 1521:
        new_lines.append(line)

content = "".join(new_lines)
# Remove unused imports
content = re.sub(r'from src\.agents\.graph import build_trip_agent\n', '', content)
content = re.sub(r'from src\.agents\.routing_decision import \([\s\S]*?validate_route,\n\)\n', '', content)
content = re.sub(r'from src\.agents\.state import TripState, initial_state\n', '', content)
content = re.sub(r'from src\.agents\.supervisor import decide_route_by_llm\n', '', content)
content = re.sub(r'from src\.api\.streaming import _DeltaGate, emit_phase, emit_reset\n', '', content)
content = re.sub(r'from src\.guardrails\.jailbreak import detect_jailbreak\n', '', content)
content = re.sub(r'from src\.i18n import SUPPORTED_LANGUAGES, t\n', 'from src.i18n import SUPPORTED_LANGUAGES\n', content)
content = re.sub(r'from src\.models\.schemas import sanitize_system_error\n', '', content)
content = re.sub(r'from src\.services\.hotel_selection import HotelPreferenceState, _has_budget_signal\n', 'from src.services.hotel_selection import HotelPreferenceState\n', content)
content = re.sub(r'from src\.services\.trip_edit_planner import TripEditPlan, TripEditPlanError, plan_trip_edit\n', '', content)
content = re.sub(r'from src\.services\.trip_intake import \([\s\S]*?_match_known_destination,\n\)\n', 'from src.services.trip_intake import TripIntakeState\n', content)
content = re.sub(r'from src\.services\.trip_planner import \([\s\S]*?resolve_trip_edit_request,\n\)\n', '', content)
content = re.sub(r'session\.agent, session\.tools = build_trip_agent\(session, checkpointer=checkpointer\)\n', 'pass\n', content)

# Remove agent and tools from TripSession constructor and attributes
content = re.sub(r'        agent: Any,\n', '', content)
content = re.sub(r'        \*,[\s\S]*?tools: Any = None,  # SessionTools — set by create_chat_session via build_trip_agent\n', '        *,\n', content)
content = re.sub(r'        self\.agent = agent\n', '', content)
content = re.sub(r'        self\.tools = tools\n', '', content)
content = re.sub(r'        agent=None,\n', '', content)

with open("backend/src/agents/session.py", "w") as f:
    f.write(content)

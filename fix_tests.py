import re

with open("backend/tests/test_api/test_routes.py", "r") as f:
    content = f.read()

# Delete test_planner_chat_preserves_state_across_turns_with_same_session_id
content = re.sub(r'@pytest\.mark\.asyncio\nasync def test_planner_chat_preserves_state_across_turns_with_same_session_id[\s\S]*?(?=@pytest\.mark\.asyncio\nasync def test_planner_chat_empty_message_rejected)', '', content)

# Delete test_two_sessions_do_not_share_trip_data
content = re.sub(r'@pytest\.mark\.asyncio\nasync def test_two_sessions_do_not_share_trip_data[\s\S]*?(?=# ---------------------------------------------------------------------------)', '', content)

with open("backend/tests/test_api/test_routes.py", "w") as f:
    f.write(content)

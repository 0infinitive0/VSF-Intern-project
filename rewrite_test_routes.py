import re

with open("backend/tests/test_api/test_routes.py", "r") as f:
    content = f.read()

# Replace _fake_planner_agent logic to mock _run_turn_via_graph instead
new_fixture = '''@pytest.fixture(autouse=True)
def _fake_planner_agent(monkeypatch):
    """Bypass LangGraph execution for routing tests."""
    from src.models.schemas import PlannerChatResponse, IntakeStatus
    from src.api.routes import _run_turn_via_graph
    
    def fake_run(session_id, message, language):
        return PlannerChatResponse(
            session_id=session_id,
            reply="Mock response",
            stage="intake",
            suggestions=[],
            trip_plan=None,
            hotel_options=None,
            intake=IntakeStatus(missing_all=True)
        )
    
    monkeypatch.setattr("src.api.routes._run_turn_via_graph", fake_run)
'''

content = re.sub(r'@pytest\.fixture\(autouse=True\)\ndef _fake_planner_agent\(monkeypatch\):[\s\S]*?(?=@pytest\.fixture)', new_fixture, content)

with open("backend/tests/test_api/test_routes.py", "w") as f:
    f.write(content)

import pytest

from src.agents.graph import agent, build_trip_agent


@pytest.mark.asyncio
async def test_agent_basic_flow():
    result = await agent.ainvoke({"query": "Hello"})
    assert "response" in result


@pytest.mark.asyncio
async def test_agent_state_structure():
    result = await agent.ainvoke({"query": "Test query"})
    assert isinstance(result, dict)
    assert "query" in result


def test_build_trip_agent_registers_exactly_the_four_agent_visible_tools():
    """generate_full_itinerary is deliberately NOT registered with
    create_react_agent — it is @tool-decorated but reachable only via
    select_hotel, which is what enforces the hotel-pick gate. Registering it
    would let the LLM bypass that gate. A behavioural check on the bound tool
    list (not a source-string match) is the guard this phase requires."""

    class _FakeSession:
        session_id = "test-session"
        pending_hotel_selection = None
        trip_data = None

    compiled_agent, tools = build_trip_agent(_FakeSession())

    tool_names = {tool.name for tool in tools}
    assert tool_names == {"recommend_hotels", "select_hotel", "modify_trip_plan", "finalize_trip_plan"}
    assert "generate_full_itinerary" not in tool_names
    assert compiled_agent is not None

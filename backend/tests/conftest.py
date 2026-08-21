from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import src.agents.graph.nodes.ask_slot as ask_slot_module
from src.main import app
from tests import llm_network_guard


def pytest_configure(config):
    """Honour TEST_SKIP_LLM before any test opens a connection."""
    if llm_network_guard.enabled():
        llm_network_guard.install()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for testing API endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_llm():
    """Mock LLM to avoid calling OpenAI during tests.

    Usage in test:
        def test_something(mock_llm):
            # LLM calls will return mock response instead of hitting OpenAI
            ...
    """
    mock = AsyncMock()
    mock.ainvoke.return_value = AsyncMock(content="Mocked LLM response")
    return mock


class _UnavailableModel:
    """A model factory result that always fails on use."""

    def invoke(self, _prompt: str):
        raise RuntimeError("no model in tests")


@pytest.fixture(autouse=True)
def slot_question_rewording_unavailable(monkeypatch):
    """`ask_slot` rewords its slot question through one `get_fast_llm` call.

    Every test in the suite runs with that model unavailable, so `ask_slot`
    returns `_render_question`'s deterministic output. Two reasons, both
    load-bearing:

    - Assertions across the suite name the fixed question strings. A model
      free to reword them would make those assertions unreproducible.
    - Under `TEST_SKIP_LLM` an un-patched call does not FAIL, it raises
      pytest's `Skipped` — so a test that quietly stopped covering its graph
      path would still report green. Forcing the fallback here is what keeps
      that from happening in the ~20 graph tests that never mention
      `ask_slot` at all.

    `tests/test_ask_slot.py` owns the rewording itself and overrides this
    per-test with `monkeypatch.setattr` in the test body.
    """
    monkeypatch.setattr(ask_slot_module, "get_fast_llm", lambda **_kwargs: _UnavailableModel())

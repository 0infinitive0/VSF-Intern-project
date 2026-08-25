"""Tests for the Airflow admin client (phase-13-airflow-client.md).

Every call is mocked at the `httpx` layer -- no live Airflow instance is
reached or needed in CI. The fixture JSON files under
plans/reports/airflow-api-fixtures/ are *real* responses captured from a
local Airflow 3.3.0 stack (see that directory's README for how and what
diverged from an Airflow-2-era guess), loaded here so parsing is proven
against real shapes rather than hand-typed ones.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from src.config import get_settings
from src.services import airflow_client

_FIXTURES = Path(__file__).resolve().parents[2] / "plans" / "reports" / "airflow-api-fixtures"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


def _response(status_code: int, body: dict | list | None = None) -> httpx.Response:
    request = httpx.Request("GET", "http://airflow.test/x")
    if body is None:
        return httpx.Response(status_code, request=request)
    return httpx.Response(status_code, json=body, request=request)


class _FakeHttp:
    """Stands in for the `httpx` module-level `post`/`request` functions.
    Responses (or exceptions, to simulate a connection failure) are queued
    in call order -- mirrors this codebase's existing fake-postgrest-client
    idiom (test_admin_hotels.py etc.), just for `httpx` instead."""

    def __init__(self) -> None:
        self.post_calls: list[dict] = []
        self.request_calls: list[dict] = []
        self._post_queue: list[httpx.Response | Exception] = []
        self._request_queue: list[httpx.Response | Exception] = []

    def queue_post(self, item: httpx.Response | Exception) -> None:
        self._post_queue.append(item)

    def queue_request(self, item: httpx.Response | Exception) -> None:
        self._request_queue.append(item)

    def post(self, url, *, json=None, timeout=None):
        self.post_calls.append({"url": url, "json": json, "timeout": timeout})
        item = self._post_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def request(self, method, url, *, json=None, params=None, headers=None, timeout=None):
        self.request_calls.append({"method": method, "url": url, "json": json, "params": params, "headers": headers, "timeout": timeout})
        item = self._request_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _queue_token(fake: _FakeHttp, token: str = "fake-jwt") -> None:
    fake.queue_post(_response(200, {"access_token": token}))


@pytest.fixture
def fake_http(monkeypatch):
    fake = _FakeHttp()
    monkeypatch.setattr(airflow_client.httpx, "post", fake.post)
    monkeypatch.setattr(airflow_client.httpx, "request", fake.request)
    return fake


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    """Points the client at a fake base and gives every test a clean token
    cache -- it's a process-wide singleton by design, so a token minted in
    one test must never leak into the next."""
    settings = get_settings()
    monkeypatch.setattr(settings, "airflow_api_base", "http://airflow.test")
    monkeypatch.setattr(settings, "airflow_username", "airflow")
    monkeypatch.setattr(settings, "airflow_password", "airflow")
    monkeypatch.setattr(settings, "airflow_request_timeout", 5.0)
    monkeypatch.setattr(airflow_client, "_token_cache", airflow_client._TokenCache())


# ---------------------------------------------------------------------------
# health() -- always returns, never raises
# ---------------------------------------------------------------------------


def test_health_connected_true_uses_real_version_fixture(fake_http):
    _queue_token(fake_http)
    version_body = _load("version.json")
    fake_http.queue_request(_response(200, version_body))

    assert airflow_client.health() == {"connected": True, "version": version_body["version"]}
    # Every network call -- token fetch included -- carries the configured
    # timeout, not just the ones that happen to be reached last.
    assert fake_http.post_calls[0]["timeout"] == 5.0
    assert fake_http.request_calls[0]["timeout"] == 5.0


def test_health_non_json_response_returns_connected_false_without_raising(fake_http):
    """A misconfigured `AIRFLOW_API_BASE` (wrong port, a reverse proxy, an
    HTML error page) answers 200 with a non-JSON body -- this must not
    escape as an uncaught `JSONDecodeError` and 500 the always-200 route."""
    _queue_token(fake_http)
    request = httpx.Request("GET", "http://airflow.test/api/v2/version")
    fake_http.queue_request(httpx.Response(200, content=b"<html>not json</html>", request=request))

    assert airflow_client.health() == {"connected": False, "reason": "airflow_unavailable"}


def test_health_non_json_token_response_returns_connected_false_without_raising(fake_http):
    request = httpx.Request("POST", "http://airflow.test/auth/token")
    fake_http.queue_post(httpx.Response(200, content=b"not json", request=request))

    assert airflow_client.health() == {"connected": False, "reason": "airflow_unavailable"}


def test_health_disabled_when_api_base_empty_makes_no_network_call(monkeypatch, fake_http):
    monkeypatch.setattr(get_settings(), "airflow_api_base", "")

    assert airflow_client.health() == {"connected": False, "reason": "airflow_unavailable"}
    assert fake_http.post_calls == []
    assert fake_http.request_calls == []


def test_health_connection_error_returns_connected_false_without_raising(fake_http):
    fake_http.queue_post(httpx.ConnectError("refused"))

    assert airflow_client.health() == {"connected": False, "reason": "airflow_unavailable"}


def test_health_timeout_returns_connected_false_without_raising(fake_http):
    fake_http.queue_post(httpx.TimeoutException("timed out"))

    assert airflow_client.health() == {"connected": False, "reason": "airflow_unavailable"}


def test_repeated_calls_against_a_dead_airflow_do_not_each_reattempt_the_connection(fake_http):
    """Without a failure cooldown, every single request against a dead
    Airflow would re-attempt the full connection/timeout, one thread at a
    time, forever. One failed fetch should short-circuit the next ones."""
    fake_http.queue_post(httpx.ConnectError("refused"))

    airflow_client.health()
    airflow_client.health()
    airflow_client.health()

    assert len(fake_http.post_calls) == 1  # not 3


# ---------------------------------------------------------------------------
# Allowlist -- checked client-side, before any network call
# ---------------------------------------------------------------------------


def test_trigger_dag_run_rejects_disallowed_dag_id_with_no_network_call(fake_http):
    with pytest.raises(airflow_client.AirflowError, match="dag_not_allowed"):
        airflow_client.trigger_dag_run("clear_airflow_history", {}, "note")

    assert fake_http.post_calls == []
    assert fake_http.request_calls == []


@pytest.mark.parametrize(
    "func",
    [
        lambda: airflow_client.get_dag("clear_airflow_history"),
        lambda: airflow_client.list_dag_runs("clear_airflow_history"),
        lambda: airflow_client.get_dag_run("clear_airflow_history", "run-1"),
        lambda: airflow_client.list_task_instances("clear_airflow_history", "run-1"),
        lambda: airflow_client.get_task_log("clear_airflow_history", "run-1", "task", 1),
    ],
)
def test_every_read_function_also_rejects_disallowed_dag_id(fake_http, func):
    """The plan's own point: allowlist is a client-tier chokepoint, not
    something only the trigger route remembers to check."""
    with pytest.raises(airflow_client.AirflowError, match="dag_not_allowed"):
        func()
    assert fake_http.post_calls == []
    assert fake_http.request_calls == []


# ---------------------------------------------------------------------------
# Token cache -- one refresh-and-retry on 401, never a loop
# ---------------------------------------------------------------------------


def test_401_triggers_one_token_refresh_and_retry_then_succeeds(fake_http):
    _queue_token(fake_http, token="stale-token")
    fake_http.queue_request(_response(401))
    _queue_token(fake_http, token="fresh-token")
    dag_body = _load("dag_detail.json")
    fake_http.queue_request(_response(200, dag_body))

    result = airflow_client.get_dag("embed_supabase_tables_pipeline")

    assert result == dag_body
    assert len(fake_http.post_calls) == 2
    assert len(fake_http.request_calls) == 2
    assert fake_http.request_calls[0]["headers"]["Authorization"] == "Bearer stale-token"
    assert fake_http.request_calls[1]["headers"]["Authorization"] == "Bearer fresh-token"


def test_second_consecutive_401_does_not_loop(fake_http):
    _queue_token(fake_http)
    fake_http.queue_request(_response(401))
    _queue_token(fake_http)
    fake_http.queue_request(_response(401))

    with pytest.raises(airflow_client.AirflowError):
        airflow_client.get_dag("embed_supabase_tables_pipeline")

    # Exactly one retry attempt, not an unbounded loop.
    assert len(fake_http.request_calls) == 2


def test_two_callers_that_both_saw_the_same_stale_401_only_refresh_once(fake_http):
    """Two concurrent requests holding the same now-stale token both get a
    401 and both call `get(stale=stale_token)`. The first legitimately
    refreshes; the second must see the cache already moved past its `stale`
    token and return the new one directly, not mint a third token."""
    cache = airflow_client._TokenCache()
    cache._token = "stale-token"
    cache._expires_at = time.monotonic() + 3600

    _queue_token(fake_http, token="fresh-token")
    first = cache.get(stale="stale-token")
    second = cache.get(stale="stale-token")  # same stale token, arrives after the refresh

    assert first == "fresh-token"
    assert second == "fresh-token"
    assert len(fake_http.post_calls) == 1


def test_token_reused_across_calls_within_ttl(fake_http):
    _queue_token(fake_http)
    fake_http.queue_request(_response(200, _load("dag_detail.json")))
    fake_http.queue_request(_response(200, _load("dagRuns_list.json")))

    airflow_client.get_dag("embed_supabase_tables_pipeline")
    airflow_client.list_dag_runs("embed_supabase_tables_pipeline")

    assert len(fake_http.post_calls) == 1  # only one token fetch for two calls


# ---------------------------------------------------------------------------
# Real-fixture shape parsing
# ---------------------------------------------------------------------------


def test_get_dag_returns_real_fixture_shape(fake_http):
    _queue_token(fake_http)
    body = _load("dag_detail.json")
    fake_http.queue_request(_response(200, body))

    result = airflow_client.get_dag("embed_supabase_tables_pipeline")

    assert result == body
    assert "is_paused" in result


def test_list_dag_runs_unwraps_the_envelope(fake_http):
    """`dagRuns` responses are `{"dag_runs": [...], "total_entries", ...}`,
    not a bare array -- this must come back as a plain list."""
    _queue_token(fake_http)
    body = _load("dagRuns_list.json")
    fake_http.queue_request(_response(200, body))

    result = airflow_client.list_dag_runs("embed_supabase_tables_pipeline")

    assert result == body["dag_runs"]


def test_get_dag_run_returns_real_fixture_shape(fake_http):
    _queue_token(fake_http)
    body = _load("trigger_response_2.json")  # same DAGRun schema as a GET
    fake_http.queue_request(_response(200, body))

    result = airflow_client.get_dag_run("embed_supabase_tables_pipeline", body["dag_run_id"])

    assert result == body


def test_list_task_instances_returns_real_fixture_shape(fake_http):
    _queue_token(fake_http)
    body = _load("taskInstances_success.json")
    fake_http.queue_request(_response(200, body))

    result = airflow_client.list_task_instances("embed_supabase_tables_pipeline", "run-1")

    assert result == body["task_instances"]
    assert all("map_index" in t for t in result)


def test_get_task_log_flattens_structured_events_and_error_detail(fake_http):
    """Real Airflow 3 log response is a list of structured JSON events, not
    plain text -- and a failing event carries `error_detail` with the actual
    exception type/message, captured live off a real ValueError."""
    _queue_token(fake_http)
    body = _load("task_log_real_failure.json")
    fake_http.queue_request(_response(200, body))

    text = airflow_client.get_task_log("embed_supabase_tables_pipeline", "run-1", "fetch_pending_hotels", 1)

    assert "Task failed with exception" in text
    assert "ValueError" in text
    assert "Missing SUPABASE_URL or SUPABASE_SERVICE_KEY" in text


def test_get_task_log_of_a_real_success_has_no_error_detail(fake_http):
    _queue_token(fake_http)
    body = _load("task_log_success.json")
    fake_http.queue_request(_response(200, body))

    text = airflow_client.get_task_log("embed_supabase_tables_pipeline", "run-1", "fetch_pending_hotels", 1)

    assert "fetched 0 pending rows" in text
    assert "ValueError" not in text


def test_get_task_log_tolerates_a_non_dict_content_entry(fake_http):
    """The log endpoint content-negotiates -- a caller-supplied `Accept`
    this client never sends, or a future Airflow version, could hand back a
    plain string entry instead of a structured event object. Must not crash."""
    _queue_token(fake_http)
    fake_http.queue_request(_response(200, {"content": ["a raw string line", {"event": "structured line"}]}))

    text = airflow_client.get_task_log("tour_pipeline", "run-1", "task", 1)

    assert text == "a raw string line\nstructured line"


def test_get_task_log_passes_map_index_as_a_query_param_not_a_path_segment(fake_http):
    """Confirmed against Airflow's own OpenAPI spec (saved as
    openapi_v2_full.json): `map_index` is `in: query`, default -1."""
    _queue_token(fake_http)
    fake_http.queue_request(_response(200, {"content": []}))

    airflow_client.get_task_log("tour_pipeline", "run-1", "some_task", 1, map_index=3)

    call = fake_http.request_calls[0]
    assert call["params"]["map_index"] == 3
    assert "/3" not in call["url"] and call["url"].endswith("/logs/1")


# ---------------------------------------------------------------------------
# trigger_dag_run -- unpauses first, requires logical_date
# ---------------------------------------------------------------------------


def test_trigger_dag_run_unpauses_then_posts_with_logical_date(fake_http):
    """A manually-triggered run on a paused DAG stays queued forever
    (verified live) -- every DAG here starts paused, so the client checks
    first and unpauses before triggering rather than leaving a portal
    admin's click stuck."""
    _queue_token(fake_http)
    fake_http.queue_request(_response(200, {"dag_id": "embed_supabase_tables_pipeline", "is_paused": True}))
    fake_http.queue_request(_response(200, {"dag_id": "embed_supabase_tables_pipeline", "is_paused": False}))
    trigger_body = _load("trigger_response_2.json")
    fake_http.queue_request(_response(200, trigger_body))

    result = airflow_client.trigger_dag_run("embed_supabase_tables_pipeline", conf={}, note="test")

    assert result == trigger_body
    get_call, patch_call, post_call = fake_http.request_calls
    assert get_call["method"] == "GET"
    assert patch_call["method"] == "PATCH"
    assert patch_call["json"] == {"is_paused": False}
    assert post_call["method"] == "POST"
    assert post_call["json"]["logical_date"].endswith("Z")
    assert "." in post_call["json"]["logical_date"]  # microsecond precision, not millisecond-truncated
    assert post_call["json"]["conf"] == {}
    assert post_call["json"]["note"] == "test"


def test_trigger_dag_run_skips_patch_when_already_unpaused(fake_http):
    """Every trigger after the first hits an already-unpaused DAG -- no
    reason to PATCH (and no reason to depend on a role that may not have
    DAG-edit permission) when nothing needs to change."""
    _queue_token(fake_http)
    fake_http.queue_request(_response(200, {"dag_id": "embed_supabase_tables_pipeline", "is_paused": False}))
    trigger_body = _load("trigger_response_2.json")
    fake_http.queue_request(_response(200, trigger_body))

    result = airflow_client.trigger_dag_run("embed_supabase_tables_pipeline")

    assert result == trigger_body
    get_call, post_call = fake_http.request_calls
    assert get_call["method"] == "GET"
    assert post_call["method"] == "POST"


def test_trigger_dag_run_aborts_before_posting_when_patch_fails(fake_http):
    """A role that can create dagRuns but not edit DAGs must not silently
    lose the trigger -- and must not fire the POST without having actually
    unpaused the DAG first."""
    _queue_token(fake_http)
    fake_http.queue_request(_response(200, {"dag_id": "embed_supabase_tables_pipeline", "is_paused": True}))
    fake_http.queue_request(_response(403))

    with pytest.raises(airflow_client.AirflowError):
        airflow_client.trigger_dag_run("embed_supabase_tables_pipeline")

    assert [c["method"] for c in fake_http.request_calls] == ["GET", "PATCH"]


# ---------------------------------------------------------------------------
# Credential hygiene
# ---------------------------------------------------------------------------


def test_airflow_password_appears_only_in_the_outgoing_auth_request_body():
    """`grep -ri airflow_password backend/src` must show it only where it's
    read to build the request Airflow itself needs -- never logged or
    returned. Code lines only (not the module docstring, which explains this
    invariant in prose)."""
    source = Path(airflow_client.__file__).read_text()
    code_lines = [line for line in source.splitlines() if "settings.airflow_password" in line]
    assert len(code_lines) == 1, f"expected exactly one code reference, found: {code_lines}"
    assert '"password": settings.airflow_password' in code_lines[0]
    assert "logger" not in code_lines[0]
    assert not code_lines[0].strip().startswith("return")

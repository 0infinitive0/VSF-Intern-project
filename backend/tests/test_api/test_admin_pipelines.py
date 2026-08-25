"""Tests for admin Pipeline health/list/trigger -- src/api/admin/pipelines.py
(phase-13-airflow-client.md health; phase-14-pipelines-list.md list/trigger).
Mocked at the `airflow_client` function boundary (not `httpx`) -- shape
parsing/allowlist/retry/token-cache logic itself is covered live and in
tests/test_airflow_client.py; this file proves pipelines.py's own logic:
catalog↔allowlist parity, the 10s list cache, per-DAG failure isolation, the
running/queued progress computation, and the trigger route's 400/409/503/202
paths.
"""

from __future__ import annotations

import pytest

from src.api.admin import pipelines as pipelines_module
from src.services import airflow_client
from src.auth import AdminUser, require_admin
from src.main import app


@pytest.fixture
def admin_override():
    app.dependency_overrides[require_admin] = lambda: AdminUser(id="admin-1", email="admin@vsftrip.vn")
    yield
    app.dependency_overrides.pop(require_admin, None)


@pytest.fixture(autouse=True)
def _fresh_list_cache():
    """The 10s cache is a module-level singleton by design (same reasoning
    as airflow_client's token cache) -- must not leak a cached response from
    one test into the next."""
    pipelines_module._list_cache.invalidate()
    yield
    pipelines_module._list_cache.invalidate()


@pytest.fixture
def no_audit(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(pipelines_module, "write_audit", lambda actor, **kwargs: calls.append({"actor": actor, **kwargs}))
    return calls


def _dag(dag_id: str, *, is_paused: bool = True, timetable_summary: str | None = "0 0 * * *") -> dict:
    return {"dag_id": dag_id, "is_paused": is_paused, "timetable_summary": timetable_summary}


def _run(run_id: str, state: str, duration: float | None = 120.0, start_date: str | None = None) -> dict:
    return {"dag_run_id": run_id, "state": state, "duration": duration, "start_date": start_date, "end_date": None}


def _mock_all_dags_empty(monkeypatch):
    """Every catalog DAG exists, is unpaused, and has no run history --
    baseline stub so tests only need to override what they actually care
    about."""
    monkeypatch.setattr(airflow_client, "get_dag", lambda dag_id: _dag(dag_id))
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: [])


# ---------------------------------------------------------------------------
# health() -- unchanged from phase 13
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_route_returns_connected_true(client, admin_override, monkeypatch):
    monkeypatch.setattr(pipelines_module.airflow_client, "health", lambda: {"connected": True, "version": "3.3.0"})

    response = await client.get("/api/v1/admin/pipelines/health")

    assert response.status_code == 200
    assert response.json() == {"connected": True, "version": "3.3.0", "reason": None}


@pytest.mark.asyncio
async def test_health_route_still_200_when_airflow_disconnected(client, admin_override, monkeypatch):
    monkeypatch.setattr(pipelines_module.airflow_client, "health", lambda: {"connected": False, "reason": "airflow_unavailable"})

    response = await client.get("/api/v1/admin/pipelines/health")

    assert response.status_code == 200
    assert response.json() == {"connected": False, "version": None, "reason": "airflow_unavailable"}


# ---------------------------------------------------------------------------
# GET /api/v1/admin/pipelines -- catalog, ordering, per-DAG isolation, cache
# ---------------------------------------------------------------------------


def test_pipeline_catalog_matches_the_allowlist_exactly():
    """The plan's own point: the catalog is "một phần của allowlist" -- if
    someone adds a DAG to one and not the other, this must fail loudly
    rather than silently drift (a DAG allowed to trigger but with no label,
    or a labeled card for a DAG that can never actually be triggered)."""
    assert set(pipelines_module._PIPELINE_CATALOG) == airflow_client.ALLOWED_DAG_IDS


@pytest.mark.asyncio
async def test_list_pipelines_returns_four_items_in_catalog_order(client, admin_override, monkeypatch):
    _mock_all_dags_empty(monkeypatch)

    response = await client.get("/api/v1/admin/pipelines")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert [item["dag_id"] for item in body["items"]] == list(pipelines_module._PIPELINE_CATALOG)
    assert [item["label"] for item in body["items"]] == ["Embedding", "Google Maps", "Tour", "Địa điểm lân cận"]


@pytest.mark.asyncio
async def test_list_pipelines_connected_false_when_airflow_unavailable(client, admin_override, monkeypatch):
    def _raise(dag_id):
        raise airflow_client.AirflowUnavailable("airflow_unavailable")

    monkeypatch.setattr(airflow_client, "get_dag", _raise)

    response = await client.get("/api/v1/admin/pipelines")

    assert response.status_code == 200
    assert response.json() == {"connected": False, "items": [], "reason": "airflow_unavailable"}


@pytest.mark.asyncio
async def test_list_pipelines_omits_a_dag_that_fails_without_500ing_the_rest(client, admin_override, monkeypatch):
    """Real live finding building this phase: `tour_pipeline` 404s in this
    environment (Airflow import error, unrelated dependency). The other 3
    real, working pipelines must still render."""

    def _get_dag(dag_id):
        if dag_id == "tour_pipeline":
            raise airflow_client.AirflowError("airflow_request_failed")
        return _dag(dag_id)

    monkeypatch.setattr(airflow_client, "get_dag", _get_dag)
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: [])

    response = await client.get("/api/v1/admin/pipelines")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert "tour_pipeline" not in {item["dag_id"] for item in body["items"]}
    assert len(body["items"]) == 3


@pytest.mark.asyncio
async def test_list_pipelines_result_is_cached_for_10_seconds(client, admin_override, monkeypatch):
    # A list (not a plain int counter) -- `_fetch_pipelines_list` calls this
    # from 4 pool threads, and `list.append` is atomic under the GIL while
    # `n += 1` on a shared int is not, so a counter here would be a flaky
    # test rather than a flaky bug.
    calls: list[str] = []

    def _get_dag(dag_id):
        calls.append(dag_id)
        return _dag(dag_id)

    monkeypatch.setattr(airflow_client, "get_dag", _get_dag)
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: [])

    for _ in range(10):
        response = await client.get("/api/v1/admin/pipelines")
        assert response.status_code == 200

    # 4 catalog DAGs fetched once, not once per request -- ten F5s must not
    # turn into 10x the Airflow load.
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_list_pipelines_refetches_after_cache_ttl_expires(client, admin_override, monkeypatch):
    calls: list[str] = []

    def _get_dag(dag_id):
        calls.append(dag_id)
        return _dag(dag_id)

    monkeypatch.setattr(airflow_client, "get_dag", _get_dag)
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: [])
    monkeypatch.setattr(pipelines_module, "_LIST_CACHE_TTL_SECONDS", 0)  # expires immediately

    await client.get("/api/v1/admin/pipelines")
    await client.get("/api/v1/admin/pipelines")

    assert len(calls) == 8


# ---------------------------------------------------------------------------
# last_run / recent_runs / progress
# ---------------------------------------------------------------------------


def test_dag_summary_last_run_is_the_newest_recent_runs_is_oldest_first(monkeypatch):
    _mock_all_dags_empty(monkeypatch)
    runs = [_run("r3", "success"), _run("r2", "success"), _run("r1", "success")]  # newest-first, as Airflow returns
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: runs)

    item = pipelines_module._dag_summary("tour_pipeline")

    assert item.last_run.run_id == "r3"
    assert [r.run_id for r in item.recent_runs] == ["r1", "r2", "r3"]


def test_progress_is_none_when_last_run_is_not_running(monkeypatch):
    _mock_all_dags_empty(monkeypatch)
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: [_run("r1", "success")])

    item = pipelines_module._dag_summary("tour_pipeline")

    assert item.last_run.progress is None


def test_progress_counts_terminal_vs_total_task_instances(monkeypatch):
    _mock_all_dags_empty(monkeypatch)
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: [_run("r1", "running", duration=None, start_date=None)])
    instances = [
        {"task_id": "a", "state": "success"},
        {"task_id": "b", "state": "success"},
        {"task_id": "c", "state": "running"},
        {"task_id": "d", "state": None},
    ]
    monkeypatch.setattr(airflow_client, "list_task_instances", lambda dag_id, run_id: instances)

    item = pipelines_module._dag_summary("tour_pipeline")

    assert item.last_run.progress.done == 2
    assert item.last_run.progress.total == 4


def test_progress_eta_hidden_without_successful_run_history(monkeypatch):
    """L56: never fabricate an ETA. No successful run to average from ->
    eta_seconds must be None, not a guess."""
    monkeypatch.setattr(airflow_client, "list_task_instances", lambda dag_id, run_id: [])
    run = _run("r1", "running", duration=None, start_date="2026-08-25T00:00:00Z")

    progress = pipelines_module._compute_progress("tour_pipeline", run, older_runs=[])

    assert progress.eta_seconds is None


def test_progress_eta_present_when_history_and_time_remaining(monkeypatch):
    monkeypatch.setattr(airflow_client, "list_task_instances", lambda dag_id, run_id: [])
    older = [_run("r0", "success", duration=100.0)]
    from datetime import UTC, datetime

    start = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    run = _run("r1", "running", duration=None, start_date=start)

    progress = pipelines_module._compute_progress("tour_pipeline", run, older_runs=older)

    assert progress.eta_seconds is not None
    assert 0 < progress.eta_seconds <= 100


def test_progress_estimates_records_only_for_embedding_and_only_from_mapped_instances(monkeypatch):
    """`estimated_records` must come from mapped (`.expand()`) instances
    only -- the unmapped fetch_pending_*/summarize_* tasks finishing must
    not, by themselves, produce a nonzero "≈N bản ghi" on a run that has
    nothing mapped (the common steady-state case: 0 pending rows)."""
    _mock_all_dags_empty(monkeypatch)
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: [_run("r1", "running", duration=None, start_date=None)])
    instances = [
        {"task_id": "fetch_pending_hotels", "state": "success", "map_index": -1},
        {"task_id": "embed_hotels", "state": "success", "map_index": 0},
        {"task_id": "embed_hotels", "state": "success", "map_index": 1},
        {"task_id": "summarize_hotels", "state": "success", "map_index": -1},
    ]
    monkeypatch.setattr(airflow_client, "list_task_instances", lambda dag_id, run_id: instances)

    embedding_item = pipelines_module._dag_summary("embed_supabase_tables_pipeline")
    other_item = pipelines_module._dag_summary("tour_pipeline")

    # 4 terminal instances total, but only 2 are mapped -> 2 * chunk size, not 4 *.
    assert embedding_item.last_run.progress.done == 4
    assert embedding_item.last_run.progress.estimated_records == 2 * pipelines_module._EMBEDDING_DEFAULT_CHUNK_SIZE
    assert other_item.last_run.progress.estimated_records is None


def test_progress_estimated_records_omitted_when_nothing_is_mapped(monkeypatch):
    """A run where 0 rows needed embedding (only unmapped tasks ran) must not
    show a fabricated "≈0 bản ghi" or "≈N bản ghi" from unmapped tasks."""
    _mock_all_dags_empty(monkeypatch)
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: [_run("r1", "running", duration=None, start_date=None)])
    instances = [{"task_id": "fetch_pending_hotels", "state": "success", "map_index": -1}]
    monkeypatch.setattr(airflow_client, "list_task_instances", lambda dag_id, run_id: instances)

    item = pipelines_module._dag_summary("embed_supabase_tables_pipeline")

    assert item.last_run.progress.estimated_records is None


# ---------------------------------------------------------------------------
# POST /api/v1/admin/pipelines/{dag_id}/runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_rejects_disallowed_dag_with_400(client, admin_override, monkeypatch):
    calls = []
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: calls.append(dag_id) or [])

    response = await client.post("/api/v1/admin/pipelines/clear_airflow_history/runs", json={})

    assert response.status_code == 400
    assert response.json() == {"detail": "dag_not_allowed"}
    assert calls == []  # never even checked run state for a disallowed id


@pytest.mark.asyncio
async def test_trigger_returns_409_when_a_run_is_already_active(client, admin_override, monkeypatch):
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: [_run("r1", "running")])
    trigger_calls = []
    monkeypatch.setattr(airflow_client, "trigger_dag_run", lambda dag_id, conf=None, note=None: trigger_calls.append(dag_id))

    response = await client.post("/api/v1/admin/pipelines/tour_pipeline/runs", json={})

    assert response.status_code == 409
    assert response.json() == {"detail": "dag_already_running"}
    assert trigger_calls == []  # never fires a second overlapping run


@pytest.mark.asyncio
async def test_trigger_returns_409_when_queued_not_just_running(client, admin_override, monkeypatch):
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: [_run("r1", "queued")])

    response = await client.post("/api/v1/admin/pipelines/tour_pipeline/runs", json={})

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_trigger_returns_503_when_airflow_unavailable(client, admin_override, monkeypatch):
    def _raise(dag_id, limit=10):
        raise airflow_client.AirflowUnavailable("airflow_unavailable")

    monkeypatch.setattr(airflow_client, "list_dag_runs", _raise)

    response = await client.post("/api/v1/admin/pipelines/tour_pipeline/runs", json={})

    assert response.status_code == 503
    assert response.json() == {"detail": "airflow_unavailable"}


@pytest.mark.asyncio
async def test_trigger_returns_502_not_500_when_airflow_rejects_the_pre_check(client, admin_override, monkeypatch):
    """Real live finding building this phase: a broken DAG (e.g. `tour_pipeline`'s
    import error before it was fixed) 404s on the Airflow side, which is an
    `AirflowError`, not `AirflowUnavailable` -- catching only the subclass
    here left this route 500ing on exactly the failure mode the list
    endpoint already handles gracefully."""

    def _raise(dag_id, limit=10):
        raise airflow_client.AirflowError("airflow_request_failed")

    monkeypatch.setattr(airflow_client, "list_dag_runs", _raise)

    response = await client.post("/api/v1/admin/pipelines/tour_pipeline/runs", json={})

    assert response.status_code == 502
    assert response.json() == {"detail": "airflow_request_failed"}


@pytest.mark.asyncio
async def test_trigger_returns_502_not_500_when_airflow_rejects_the_trigger_itself(client, admin_override, monkeypatch):
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: [])

    def _raise(dag_id, conf=None, note=None):
        raise airflow_client.AirflowError("airflow_request_failed")

    monkeypatch.setattr(airflow_client, "trigger_dag_run", _raise)

    response = await client.post("/api/v1/admin/pipelines/tour_pipeline/runs", json={})

    assert response.status_code == 502
    assert response.json() == {"detail": "airflow_request_failed"}


@pytest.mark.asyncio
async def test_trigger_rejects_conf_for_a_dag_with_no_params(client, admin_override, monkeypatch):
    """Only Embedding (`has_params: True`) may take a non-empty `conf` --
    the other 3 DAGs declare no `params` block, so an admin-supplied key
    would reach a task's `dag_run.conf` completely unvalidated."""
    calls = []
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: calls.append(dag_id) or [])

    response = await client.post("/api/v1/admin/pipelines/tour_pipeline/runs", json={"conf": {"item_limit": 999999999}})

    assert response.status_code == 422
    assert response.json() == {"detail": "pipeline_has_no_params"}
    assert calls == []  # rejected before even checking run state


@pytest.mark.asyncio
async def test_trigger_allows_conf_for_the_embedding_dag(client, admin_override, monkeypatch, no_audit):
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: [])
    monkeypatch.setattr(airflow_client, "trigger_dag_run", lambda dag_id, conf=None, note=None: {"dag_run_id": "manual__x", "state": "queued"})

    response = await client.post("/api/v1/admin/pipelines/embed_supabase_tables_pipeline/runs", json={"conf": {"only_null": False}})

    assert response.status_code == 202


@pytest.mark.asyncio
async def test_trigger_succeeds_writes_audit_and_invalidates_cache(client, admin_override, monkeypatch, no_audit):
    monkeypatch.setattr(airflow_client, "list_dag_runs", lambda dag_id, limit=10: [_run("r0", "success")])
    monkeypatch.setattr(airflow_client, "trigger_dag_run", lambda dag_id, conf=None, note=None: {"dag_run_id": "manual__x", "state": "queued"})
    # Prime the cache with a stale value so we can prove trigger invalidates it.
    monkeypatch.setattr(airflow_client, "get_dag", lambda dag_id: _dag(dag_id))
    await client.get("/api/v1/admin/pipelines")
    assert pipelines_module._list_cache._value is not None

    response = await client.post("/api/v1/admin/pipelines/tour_pipeline/runs", json={"conf": {}})

    assert response.status_code == 202
    assert response.json() == {"dag_id": "tour_pipeline", "run_id": "manual__x", "state": "queued"}
    assert no_audit[0]["action"] == "pipeline.trigger"
    assert no_audit[0]["entity_id"] == "tour_pipeline"
    assert no_audit[0]["after"] == {"dag_id": "tour_pipeline", "conf": {}, "run_id": "manual__x"}
    assert pipelines_module._list_cache._value is None  # invalidated, not left stale


def test_list_cache_invalidate_during_in_flight_fetch_is_not_lost(monkeypatch):
    """Regression: a fetch already in flight when `invalidate()` fires must
    not re-populate the cache with its now-stale result afterwards -- that
    would silently undo the invalidation `trigger_pipeline_run` just asked
    for, and a poll right after triggering would see the pre-trigger
    snapshot again instead of the new run."""
    cache = pipelines_module._ListCache()
    stale_response = pipelines_module.PipelinesListResponse(connected=True, items=[])

    def _slow_fetch():
        cache.invalidate()  # simulates another request invalidating mid-fetch
        return stale_response

    monkeypatch.setattr(pipelines_module, "_fetch_pipelines_list", _slow_fetch)

    result = cache.get()

    assert result is stale_response  # the caller in flight still gets an answer
    assert cache._value is None  # but it must not be cached as the current one

"""Admin Pipeline (C1-C3, phase-14/15/16-*.md) Airflow REST client
(phase-13-airflow-client.md).

Talks to Airflow 3.3.0's `/api/v2` -- built against real captured responses in
`plans/reports/airflow-api-fixtures/` (that directory's README lists every
place the real API diverged from an Airflow-2-era guess: `logical_date` is
required on trigger, dagRuns list responses are envelopes not arrays, and
task logs are a list of structured JSON events, not plain text). Re-check
that fixture set before "fixing" any shape here.

Portal users have no Airflow account of their own (decision #4) -- credential
handling stays entirely server-side. `airflow_username`/`airflow_password`
never appear in any response this module returns, and `AirflowError` messages
are always a short fixed string, never Airflow's raw response body (which can
contain internal hostnames, stack traces, DB connection details).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)

# The only DAGs a portal admin may ever trigger (plan's F5: 4 real business
# DAGs, not the 7 the original design prompt assumed -- the other files under
# dags/data_pipeline/ are library modules, not DAGs, and clear_airflow_history
# is housekeeping deliberately excluded here).
ALLOWED_DAG_IDS = frozenset(
    {
        "embed_supabase_tables_pipeline",
        "google_maps_poc_attractions_pipeline_supabase",
        "hotel_nearby_attractions_pipeline_supabase",
        "tour_pipeline",
    }
)

# Real token TTL captured live is 24h (iat/exp fixture in airflow-api-fixtures/
# auth_token_shape.json) -- refreshed well before that so a near-expiry token
# is never handed to a caller.
_TOKEN_TTL_SECONDS = 23 * 3600

# After a failed token fetch, skip re-attempting Airflow for this long instead
# of every single request re-trying the full `airflow_request_timeout` against
# a host that's already known to be down.
_FAILURE_COOLDOWN_SECONDS = 30


class AirflowError(RuntimeError):
    """Safe to surface as an HTTP error `detail` -- never wraps Airflow's raw
    response body."""


class AirflowUnavailable(AirflowError):
    """Airflow unreachable, timed out, not configured (`airflow_api_base`
    empty), or answering with something that isn't valid JSON."""


def _check_allowed(dag_id: str) -> None:
    if dag_id not in ALLOWED_DAG_IDS:
        raise AirflowError("dag_not_allowed")


class _TokenCache:
    """Process-wide JWT cache. Sync `def` routes share one anyio threadpool
    (default 40 workers) -- the lock here only ever protects the small
    in-memory read/write of `_token`/`_expires_at`/`_failed_until`, never the
    blocking HTTP call itself, so a slow or dead Airflow cannot serialize
    every other admin route's threads behind this one cache. A failed fetch
    is cached too (`_failed_until`): without that, every request against a
    dead Airflow re-attempts the connection for the full timeout, one at a
    time, forever."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._failed_until: float = 0.0

    def get(self, *, stale: str | None = None) -> str:
        """`stale`: the token a caller just got a 401 for -- forces a
        refresh, but only if no other thread already refreshed past it
        (avoids every thread that saw the same 401 each minting its own new
        token one after another)."""
        with self._lock:
            now = time.monotonic()
            if stale is None:
                if self._token is not None and now < self._expires_at:
                    return self._token
            elif self._token is not None and self._token != stale:
                return self._token
            if now < self._failed_until:
                raise AirflowUnavailable("airflow_unavailable")

        try:
            token = self._fetch()
        except AirflowUnavailable:
            with self._lock:
                self._failed_until = time.monotonic() + _FAILURE_COOLDOWN_SECONDS
            raise

        with self._lock:
            self._token = token
            self._expires_at = time.monotonic() + _TOKEN_TTL_SECONDS
            self._failed_until = 0.0
        return token

    @staticmethod
    def _fetch() -> str:
        settings = get_settings()
        try:
            response = httpx.post(
                f"{settings.airflow_api_base}/auth/token",
                json={"username": settings.airflow_username, "password": settings.airflow_password},
                timeout=settings.airflow_request_timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AirflowUnavailable("airflow_unavailable") from exc
        try:
            token = response.json().get("access_token")
        except ValueError as exc:  # json.JSONDecodeError subclasses ValueError
            raise AirflowUnavailable("airflow_unavailable") from exc
        if not token:
            raise AirflowUnavailable("airflow_unavailable")
        return token


_token_cache = _TokenCache()


def _request(method: str, path: str, *, json_body: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> Any:
    """Every call goes through here: `airflow_api_base` empty short-circuits
    before any network attempt, every request carries
    `airflow_request_timeout`, and a 401 gets exactly one refresh-and-retry
    (not a loop -- a second 401 is a real auth failure)."""
    settings = get_settings()
    if not settings.airflow_api_base:
        raise AirflowUnavailable("airflow_unavailable")

    url = f"{settings.airflow_api_base}{path}"

    def _send(token: str) -> httpx.Response:
        try:
            return httpx.request(
                method,
                url,
                json=json_body,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=settings.airflow_request_timeout,
            )
        except httpx.HTTPError as exc:
            raise AirflowUnavailable("airflow_unavailable") from exc

    first_token = _token_cache.get()
    response = _send(first_token)
    if response.status_code == 401:
        response = _send(_token_cache.get(stale=first_token))

    if response.status_code >= 400:
        logger.warning("Airflow API error: %s %s -> %s", method, path, response.status_code)
        raise AirflowError("airflow_request_failed")

    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:  # json.JSONDecodeError subclasses ValueError
        raise AirflowError("airflow_bad_response") from exc


def _request_dict(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    """Same as `_request`, but for endpoints that always answer with a JSON
    object -- an unexpected empty/non-object body becomes a clear
    `AirflowError` instead of a `None`/list silently reaching a caller typed
    to expect `dict[str, Any]`."""
    data = _request(method, path, **kwargs)
    if not isinstance(data, dict):
        raise AirflowError("airflow_bad_response")
    return data


def get_dag(dag_id: str) -> dict[str, Any]:
    _check_allowed(dag_id)
    return _request_dict("GET", f"/api/v2/dags/{dag_id}")


def list_dag_runs(dag_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """`dagRuns` is an envelope (`{"dag_runs": [...], "total_entries", ...}`),
    not a bare array -- unwrapped here so callers get a plain list."""
    _check_allowed(dag_id)
    data = _request("GET", f"/api/v2/dags/{dag_id}/dagRuns", params={"limit": limit, "order_by": "-start_date"})
    return data.get("dag_runs", []) if isinstance(data, dict) else []


def get_dag_run(dag_id: str, run_id: str) -> dict[str, Any]:
    _check_allowed(dag_id)
    return _request_dict("GET", f"/api/v2/dags/{dag_id}/dagRuns/{quote(run_id, safe='')}")


def trigger_dag_run(dag_id: str, conf: dict[str, Any] | None = None, note: str | None = None) -> dict[str, Any]:
    """A manually-triggered run on a *paused* DAG stays `queued` forever --
    verified live, the scheduler never dispatches it. Every DAG here starts
    paused (`AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: true`), and a portal
    admin has no Airflow UI to unpause it themselves (decision #4), so this
    checks first and only unpauses when actually needed -- one click always
    actually runs, and a DAG that's already unpaused (every trigger after the
    first) never depends on a PATCH the calling role might not have
    permission for. Phase 15's confirm dialog should disclose that triggering
    a currently-paused DAG also resumes its own schedule (e.g.
    `embed_supabase_tables_pipeline`'s `@daily`) going forward -- this client
    has no way to undo that, by the same decision #4.

    `logical_date` is required by Airflow's own `TriggerDAGRunPostBody`
    schema (nullable in type, but `required` -- untested live with an
    explicit `null`), so this always supplies `now()` at full microsecond
    precision (not millisecond-truncated) so two rapid triggers can't collide
    on the same value.
    """
    _check_allowed(dag_id)
    dag = get_dag(dag_id)
    if dag.get("is_paused"):
        _request("PATCH", f"/api/v2/dags/{dag_id}", json_body={"is_paused": False})
    logical_date = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return _request_dict(
        "POST",
        f"/api/v2/dags/{dag_id}/dagRuns",
        json_body={"logical_date": logical_date, "conf": conf or {}, "note": note},
    )


def list_task_instances(dag_id: str, run_id: str) -> list[dict[str, Any]]:
    _check_allowed(dag_id)
    data = _request("GET", f"/api/v2/dags/{dag_id}/dagRuns/{quote(run_id, safe='')}/taskInstances")
    return data.get("task_instances", []) if isinstance(data, dict) else []


def get_task_log(dag_id: str, run_id: str, task_id: str, try_number: int, map_index: int = -1) -> str:
    """Airflow 3's log response is a list of structured JSON events
    (`{"content": [{"event": "...", "error_detail": [...]?, ...}], ...}`),
    not plain text -- flattened here into one string (one line per event,
    with a failing event's `error_detail` exception type/message appended)
    since no screen needs the structured form yet. `map_index` is a query
    parameter on this endpoint (confirmed against Airflow's own OpenAPI spec),
    not a path segment."""
    _check_allowed(dag_id)
    data = _request(
        "GET",
        f"/api/v2/dags/{dag_id}/dagRuns/{quote(run_id, safe='')}/taskInstances/{quote(task_id, safe='')}/logs/{try_number}",
        params={"map_index": map_index, "full_content": "true"},
    )
    content = data.get("content", []) if isinstance(data, dict) else []
    lines: list[str] = []
    for entry in content:
        if not isinstance(entry, dict):
            lines.append(str(entry))
            continue
        line = entry.get("event", "")
        for exc in entry.get("error_detail") or []:
            line = f"{line}: {exc.get('exc_type')}: {exc.get('exc_value')}"
        lines.append(line)
    return "\n".join(lines)


def health() -> dict[str, Any]:
    """Always returns -- never raises -- since this is a status answer, not a
    request that can fail (phase-13's `GET /admin/pipelines/health` contract).
    Uses `/api/v2/version` rather than `/api/v2/monitor/health`: a successful
    call already proves connectivity, and this gives the version string in
    the same round trip instead of parsing four component sub-statuses."""
    try:
        data = _request("GET", "/api/v2/version")
    except AirflowError:
        return {"connected": False, "reason": "airflow_unavailable"}
    return {"connected": True, "version": data.get("version") if isinstance(data, dict) else None}

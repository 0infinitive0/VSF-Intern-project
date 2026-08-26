"""Admin Pipeline branch (C1-C3, phase-14/15/16-*.md).

Phase 13 shipped only the health check. Phase 14 (C1, this file's list/
trigger endpoints) replaces the Airflow UI for the ops team entirely
(decision #4) -- portal users don't know what a DAG is, so nothing here ever
surfaces `dag_id` or an Airflow term. `_PIPELINE_CATALOG` is the one place
that maps the 4 real DAGs (phase-13's `airflow_client.ALLOWED_DAG_IDS`) to
their Vietnamese label/description; `test_admin_pipelines.py` asserts the two
sets stay identical so the allowlist and the catalog can never drift apart.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api.admin.audit import write_audit
from src.auth import AdminUser, require_admin
from src.services import airflow_client

logger = logging.getLogger(__name__)

pipelines_router = APIRouter(prefix="/pipelines", tags=["admin-pipelines"])

# Labels/descriptions in plain Vietnamese, no `dag_id` anywhere on screen
# (plan's "Ranh giới không được vượt"). Dict order is display order (matches
# the design's card order): Embedding, Google Maps, Tour, Địa điểm lân cận.
# `has_params` marks the one pipeline (Embedding) whose "Chạy" button opens a
# real options dialog (Phase 15, C2) instead of a one-line confirm.
_PIPELINE_CATALOG: dict[str, dict[str, Any]] = {
    "embed_supabase_tables_pipeline": {
        "label": "Embedding",
        "description": "Dạy bot học lại dữ liệu khách sạn, phòng và địa điểm",
        "has_params": True,
    },
    "google_maps_poc_attractions_pipeline_supabase": {
        "label": "Google Maps",
        "description": "Cập nhật toạ độ, đánh giá và ảnh từ Google Maps",
        "has_params": False,
    },
    "tour_pipeline": {
        "label": "Tour",
        "description": "Đồng bộ tour và hoạt động quanh khách sạn",
        "has_params": False,
    },
    "hotel_nearby_attractions_pipeline_supabase": {
        "label": "Địa điểm lân cận",
        "description": "Tính các điểm đáng chú ý gần mỗi khách sạn",
        "has_params": False,
    },
}

_RUNNING_STATES = frozenset({"running", "queued"})
_TERMINAL_TASK_STATES = frozenset({"success", "failed", "skipped", "upstream_failed", "removed"})
# `embed_supabase_dag.py`'s own documented default for `embed_supabase_chunk_size`
# (Variable unset in this environment -- confirmed live, phase 13). Only used
# to turn "N chunks done" into an approximate record count for the embedding
# card (L57); wrong if that Variable is ever overridden away from 25.
_EMBEDDING_DEFAULT_CHUNK_SIZE = 25

# Was 10s; lowered so the hotel-detail-page reembed progress banner (polling
# every 1s) actually sees state changes promptly instead of the cache masking
# them for up to 10s -- still dedupes any burst of requests inside the same
# ~2s window, just no longer at the cost of near-real-time progress/success.
_LIST_CACHE_TTL_SECONDS = 2


class PipelinesHealthResponse(BaseModel):
    connected: bool
    version: str | None = None
    reason: Literal["airflow_unavailable"] | None = None


@pipelines_router.get("/health", response_model=PipelinesHealthResponse)
def get_pipelines_health() -> PipelinesHealthResponse:
    """Always `200` -- this is a status answer for the UI's connection
    banner, not a request that fails (phase-13's contract)."""
    return PipelinesHealthResponse(**airflow_client.health())


class PipelineProgress(BaseModel):
    done: int
    total: int
    eta_seconds: int | None = None
    # L57: "N/M bước đã xong" is the real contract; this is a labeled ≈
    # estimate on top, embedding only.
    estimated_records: int | None = None


class PipelineLastRun(BaseModel):
    run_id: str
    state: str | None
    start_date: str | None
    end_date: str | None
    duration_seconds: int | None = None
    progress: PipelineProgress | None = None


class PipelineRunSummary(BaseModel):
    run_id: str
    state: str | None
    duration_seconds: int | None = None


class PipelineItem(BaseModel):
    dag_id: str
    label: str
    description: str
    is_paused: bool
    schedule: str | None = None
    has_params: bool
    last_run: PipelineLastRun | None = None
    recent_runs: list[PipelineRunSummary] = Field(default_factory=list)


class PipelinesListResponse(BaseModel):
    connected: bool
    items: list[PipelineItem]
    reason: Literal["airflow_unavailable"] | None = None


def _run_summary(run: dict[str, Any]) -> PipelineRunSummary:
    duration = run.get("duration")
    return PipelineRunSummary(
        run_id=run["dag_run_id"],
        state=run.get("state"),
        duration_seconds=round(duration) if duration is not None else None,
    )


def _compute_progress(dag_id: str, run: dict[str, Any], older_runs: list[dict[str, Any]]) -> PipelineProgress | None:
    """`done`/`total` count task instances by terminal-vs-not (works whether
    or not any task is mapped -- the one thing phase 13 couldn't verify live
    was a real mapped-task run, so this deliberately doesn't assume a
    particular `map_index` shape). `eta_seconds` is average duration of
    recent successful runs minus elapsed time -- omitted (not a fabricated
    number) whenever there isn't at least one successful run to average, or
    the estimate would already be negative (L56)."""
    if run.get("state") != "running":
        return None

    instances = airflow_client.list_task_instances(dag_id, run["dag_run_id"])
    total = len(instances)
    done = sum(1 for t in instances if t.get("state") in _TERMINAL_TASK_STATES)

    eta_seconds: int | None = None
    successful_durations = [r["duration"] for r in older_runs if r.get("state") == "success" and r.get("duration") is not None]
    start_date = run.get("start_date")
    if successful_durations and start_date:
        avg_duration = sum(successful_durations) / len(successful_durations)
        started = datetime.fromisoformat(str(start_date).replace("Z", "+00:00"))
        elapsed = max(0.0, (datetime.now(UTC) - started).total_seconds())  # clock skew must not inflate the ETA
        remaining = avg_duration - elapsed
        if remaining > 0:
            eta_seconds = round(remaining)

    # Only mapped instances (`map_index >= 0`, i.e. `embed_hotels.expand(...)`
    # and friends) represent an actual chunk of records -- the unmapped
    # fetch_pending_*/summarize_* tasks in `done` would otherwise inflate
    # this to a nonzero, fabricated count even on a run with 0 pending rows
    # (exactly the common steady-state case), which is the L56/L57 violation
    # this field exists to avoid.
    mapped_done = sum(1 for t in instances if t.get("state") in _TERMINAL_TASK_STATES and t.get("map_index", -1) >= 0)
    estimated_records = mapped_done * _EMBEDDING_DEFAULT_CHUNK_SIZE if dag_id == "embed_supabase_tables_pipeline" and mapped_done > 0 else None
    return PipelineProgress(done=done, total=total, eta_seconds=eta_seconds, estimated_records=estimated_records)


def _dag_summary(dag_id: str) -> PipelineItem:
    meta = _PIPELINE_CATALOG[dag_id]
    dag = airflow_client.get_dag(dag_id)
    runs = airflow_client.list_dag_runs(dag_id, limit=10)  # newest first (order_by=-start_date)

    last_run: PipelineLastRun | None = None
    if runs:
        run = runs[0]
        duration = run.get("duration")
        last_run = PipelineLastRun(
            run_id=run["dag_run_id"],
            state=run.get("state"),
            start_date=run.get("start_date"),
            end_date=run.get("end_date"),
            duration_seconds=round(duration) if duration is not None else None,
            progress=_compute_progress(dag_id, run, runs[1:]),
        )

    return PipelineItem(
        dag_id=dag_id,
        label=meta["label"],
        description=meta["description"],
        is_paused=bool(dag.get("is_paused")),
        schedule=dag.get("timetable_summary"),
        has_params=meta["has_params"],
        last_run=last_run,
        recent_runs=[_run_summary(r) for r in reversed(runs)],  # oldest first, for the sparkline
    )


def _dag_summary_or_none(dag_id: str) -> PipelineItem | None:
    """One DAG that 404s, has an import error, or is otherwise broken in
    Airflow must not 500 the whole list -- the other 3 still have real,
    clickable cards. Same principle as L53 (never draw a card for a pipeline
    that doesn't actually work), just applied to a DAG that turns out broken
    at runtime instead of one that was never real to begin with.
    `AirflowUnavailable` is NOT caught here -- that means Airflow itself is
    down, which is `_fetch_pipelines_list`'s job to turn into
    `connected: false` for the whole response, not a per-card omission."""
    try:
        return _dag_summary(dag_id)
    except airflow_client.AirflowUnavailable:
        # Airflow itself is unreachable, not just this one DAG -- let
        # `_fetch_pipelines_list` turn this into `connected: false` for the
        # whole response instead of an empty-but-"connected" one.
        raise
    except airflow_client.AirflowError as exc:
        logger.warning("Pipeline %s: failed to summarize, omitting from the list (%s)", dag_id, exc)
        return None


def _fetch_pipelines_list() -> PipelinesListResponse:
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(_PIPELINE_CATALOG)) as pool:
            items = [item for item in pool.map(_dag_summary_or_none, _PIPELINE_CATALOG.keys()) if item is not None]
    except airflow_client.AirflowUnavailable:
        return PipelinesListResponse(connected=False, items=[], reason="airflow_unavailable")
    return PipelinesListResponse(connected=True, items=items)


class _ListCache:
    """10s cache so ten admins mashing F5 don't turn into ten×8 Airflow
    requests (plan's own success criterion). Same double-checked-locking
    shape as `airflow_client._TokenCache` -- the lock only ever guards the
    tiny in-memory read/write, the actual 4-DAG parallel fetch happens
    outside it, so a slow Airflow can't serialize concurrent pollers behind
    this cache the way it would if the lock wrapped the fetch itself."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: PipelinesListResponse | None = None
        self._fetched_at: float = 0.0
        self._generation = 0

    def get(self) -> PipelinesListResponse:
        with self._lock:
            if self._value is not None and time.monotonic() < self._fetched_at + _LIST_CACHE_TTL_SECONDS:
                return self._value
            generation = self._generation
        fresh = _fetch_pipelines_list()
        with self._lock:
            # Only store if nobody invalidated while this fetch was in
            # flight -- otherwise a pre-trigger snapshot could land *after*
            # `invalidate()` and get cached as if it were still current,
            # silently un-doing the invalidation `trigger_pipeline_run` just
            # asked for.
            if generation == self._generation:
                self._value = fresh
                self._fetched_at = time.monotonic()
        return fresh

    def invalidate(self) -> None:
        with self._lock:
            self._value = None
            self._fetched_at = 0.0
            self._generation += 1


_list_cache = _ListCache()


def invalidate_pipelines_cache() -> None:
    """Public entrypoint for other admin routes that trigger a DAG run
    outside this router (`embedding.py`'s `POST /hotels/reembed`, which
    shares `embed_supabase_tables_pipeline` with the "Chạy embedding" button
    here) -- without this, a poller reading `GET /pipelines` right after such
    a trigger can see a stale snapshot for up to `_LIST_CACHE_TTL_SECONDS`."""
    _list_cache.invalidate()


@pipelines_router.get("", response_model=PipelinesListResponse)
def list_pipelines() -> PipelinesListResponse:
    return _list_cache.get()


class TriggerRunRequest(BaseModel):
    conf: dict[str, Any] = Field(default_factory=dict)


class TriggerRunResponse(BaseModel):
    dag_id: str
    run_id: str
    state: str


@pipelines_router.post("/{dag_id}/runs", response_model=TriggerRunResponse, status_code=202)
def trigger_pipeline_run(dag_id: str, body: TriggerRunRequest, admin: AdminUser = Depends(require_admin)) -> TriggerRunResponse | JSONResponse:
    """`dag_id` is checked here **and** inside `airflow_client` (plan's own
    "cả route và client") -- this route's check produces the clean `400` the
    spec wants; the client's is the chokepoint that can never be forgotten
    by a future caller. The running/queued check is a live call, never the
    10s list cache -- running a crawl pipeline twice at once is the fastest
    way to get IP-blocked by an OTA and pay for the same API calls twice.
    (A second guard against the same overlap: all 4 DAGs set
    `max_active_runs=1` in Airflow itself, so even a concurrent-POST race
    that gets past this check can't make Airflow execute two runs at once --
    the loser just queues behind the winner instead of running in parallel.)

    Only `has_params` DAGs (Embedding, today) may pass a non-empty `conf` --
    the other 3 have no `params` block in their DAG, so an admin-supplied key
    would reach a task's `dag_run.conf` with no validation at all."""
    if dag_id not in _PIPELINE_CATALOG:
        return JSONResponse(status_code=400, content={"detail": "dag_not_allowed"})

    if body.conf and not _PIPELINE_CATALOG[dag_id]["has_params"]:
        return JSONResponse(status_code=422, content={"detail": "pipeline_has_no_params"})

    try:
        current_runs = airflow_client.list_dag_runs(dag_id, limit=1)
    except airflow_client.AirflowUnavailable:
        return JSONResponse(status_code=503, content={"detail": "airflow_unavailable"})
    except airflow_client.AirflowError:
        return JSONResponse(status_code=502, content={"detail": "airflow_request_failed"})

    if current_runs and current_runs[0].get("state") in _RUNNING_STATES:
        return JSONResponse(status_code=409, content={"detail": "dag_already_running"})

    try:
        result = airflow_client.trigger_dag_run(dag_id, conf=body.conf)
    except airflow_client.AirflowUnavailable:
        return JSONResponse(status_code=503, content={"detail": "airflow_unavailable"})
    except airflow_client.AirflowError:
        return JSONResponse(status_code=502, content={"detail": "airflow_request_failed"})

    run_id = result.get("dag_run_id", "")
    write_audit(
        admin,
        action="pipeline.trigger",
        entity_type="pipeline",
        entity_id=dag_id,
        after={"dag_id": dag_id, "conf": body.conf, "run_id": run_id},
    )
    _list_cache.invalidate()  # a poll right after triggering should see the new run, not a stale 10s-old snapshot

    return TriggerRunResponse(dag_id=dag_id, run_id=run_id, state=result.get("state", "queued"))

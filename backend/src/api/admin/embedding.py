"""Admin B7/C4 -- Trạng thái & độ phủ embedding (phase-12-embedding-status.md).

Only three tables carry an `embedding` column and feed the bot's search:
`hotels`, `rooms`, `attractions` (`TABLE_COLUMNS` in
`src/airflow/dags/data_pipeline/embed_supabase_dag.py`). `room_prices` has no
embedding column and must never appear here (plan's grep-checked success
criterion).

`POST /hotels/reembed` is the one reembed trigger for every caller: B1's bulk
bar, B7's row action, and B3/B5's post-save dialogs (phase-09/10, which
previously called a since-removed `POST /hotels/{hotel_id}/reembed` stub --
this replaces it with `hotel_ids: [hotel_id]`). It always does step 1 (clear
`embedding` to NULL, which alone has real value: the next `@daily` `only_null`
run picks the row up regardless), then does step 2 -- trigger
`embed_supabase_tables_pipeline` via Phase 13's Airflow client, passing
`hotel_ids`/`include_rooms` as the trigger `conf`. The DAG
(`embed_supabase_dag.py`'s `fetch_pending_rows_task`) reads that conf and, when
present, scopes the run to exactly those hotels (and their rooms only if
`include_rooms`) instead of sweeping every pending row in the system --
`queued: false` only means Airflow itself couldn't be reached/errored.

Always triggers a fresh run rather than checking for one already in flight:
the DAG's own `max_active_runs=1` queues a second trigger behind the first
instead of erroring, and an already-running run may have started with
different (or no) `hotel_ids` conf and would silently never pick up this
request's hotels otherwise.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from src.api.admin.audit import write_audit
from src.api.admin.pipelines import invalidate_pipelines_cache
from src.auth import AdminUser, require_admin
from src.clients.supabase_client import get_supabase_client
from src.services import airflow_client

embedding_router = APIRouter(tags=["admin-embedding"])

# Same DAG `pipelines.py`'s `_PIPELINE_CATALOG["embed_supabase_tables_pipeline"]`
# triggers for the "Embedding" pipeline card -- one shared re-embed run, not a
# second parallel trigger path.
_EMBED_DAG_ID = "embed_supabase_tables_pipeline"

EmbeddedTable = Literal["hotels", "rooms", "attractions"]

_TABLE_LABELS: dict[EmbeddedTable, str] = {"hotels": "Khách sạn", "rooms": "Phòng", "attractions": "Địa điểm"}


class EmbeddingTableSummary(BaseModel):
    table: EmbeddedTable
    label: str
    total: int
    embedded: int
    missing: int


class EmbeddingSummaryResponse(BaseModel):
    tables: list[EmbeddingTableSummary]
    total_missing: int


class EmbeddingMissingItem(BaseModel):
    id: str
    name: str
    hotel_name: str | None = None
    updated_at: str | None = None


class EmbeddingMissingResponse(BaseModel):
    items: list[EmbeddingMissingItem]


class ReembedHotelsRequest(BaseModel):
    hotel_ids: list[str] = Field(min_length=1)
    include_rooms: bool = False


class ReembedHotelsResponse(BaseModel):
    cleared_hotels: int
    cleared_rooms: int
    dag_run_id: str | None = None
    queued: bool
    detail: str | None = None


def _count(table: EmbeddedTable, *, missing: bool) -> int:
    """`count="exact"` + `range(0, 0)` (inclusive, so one row at most) keeps
    the body negligible while the exact count still comes from the
    Content-Range header -- same idiom as orders.py's stat queries."""
    query = get_supabase_client().table(table).select("id", count="exact")
    if missing:
        query = query.is_("embedding", "null")
    return query.range(0, 0).execute().count or 0


@embedding_router.get("/embedding/summary", response_model=EmbeddingSummaryResponse)
def get_embedding_summary() -> EmbeddingSummaryResponse:
    tables: list[EmbeddingTableSummary] = []
    total_missing = 0
    for table, label in _TABLE_LABELS.items():
        total = _count(table, missing=False)
        missing = _count(table, missing=True)
        tables.append(EmbeddingTableSummary(table=table, label=label, total=total, embedded=total - missing, missing=missing))
        total_missing += missing
    return EmbeddingSummaryResponse(tables=tables, total_missing=total_missing)


@embedding_router.get("/embedding/missing", response_model=EmbeddingMissingResponse)
def get_embedding_missing(table: EmbeddedTable = Query(...), limit: int = Query(20, ge=1, le=100)) -> EmbeddingMissingResponse:
    client = get_supabase_client()
    if table == "rooms":
        # Embedded select (`hotels(name)`) -- same PostgREST join idiom as
        # hotels.py's blocking-bookings lookup.
        rows = (
            client.table("rooms")
            .select("id,name,updated_at,hotels(name)")
            .is_("embedding", "null")
            # `updated_at` is nullable and postgrest defaults DESC to NULLS
            # FIRST -- without this, null rows crowd out the genuine most-
            # recently-touched ones this endpoint exists to surface.
            .order("updated_at", desc=True, nullsfirst=False)
            .limit(limit)
            .execute()
            .data
            or []
        )
        items = [
            EmbeddingMissingItem(
                id=row["id"],
                name=row["name"],
                hotel_name=(row.get("hotels") or {}).get("name"),
                updated_at=row.get("updated_at"),
            )
            for row in rows
        ]
    else:
        rows = (
            client.table(table)
            .select("id,name,updated_at")
            .is_("embedding", "null")
            .order("updated_at", desc=True, nullsfirst=False)
            .limit(limit)
            .execute()
            .data
            or []
        )
        items = [EmbeddingMissingItem(id=row["id"], name=row["name"], updated_at=row.get("updated_at")) for row in rows]
    return EmbeddingMissingResponse(items=items)


@embedding_router.post("/hotels/reembed", response_model=ReembedHotelsResponse)
def reembed_hotels(body: ReembedHotelsRequest, admin: AdminUser = Depends(require_admin)) -> ReembedHotelsResponse:
    client = get_supabase_client()
    # `returning="minimal"` -- a 25-hotel bulk clear has no reason to pull
    # every column of every touched row back over the wire just to discard
    # it; `count="exact"` still reports the affected-row count from the
    # Content-Range header regardless of `returning`.
    cleared_hotels = (
        client.table("hotels").update({"embedding": None}, count="exact", returning="minimal").in_("id", body.hotel_ids).execute().count or 0
    )
    cleared_rooms = 0
    if body.include_rooms:
        cleared_rooms = (
            client.table("rooms")
            .update({"embedding": None}, count="exact", returning="minimal")
            .in_("hotel_id", body.hotel_ids)
            .execute()
            .count
            or 0
        )

    # One row per hotel, not one joined row for the whole batch: every other
    # admin write here logs per-entity (bulk_set_hotel_active loops the same
    # way), and `admin_audit_log` is indexed on (entity_type, entity_id) --
    # a comma-joined id would make "who cleared hotel X's embedding"
    # unanswerable by that index.
    for hotel_id in body.hotel_ids:
        write_audit(
            admin,
            action="embedding.reembed",
            entity_type="hotel",
            entity_id=hotel_id,
            after={"hotel_ids": body.hotel_ids, "cleared_hotels": cleared_hotels, "cleared_rooms": cleared_rooms},
        )

    # Step 2: actually run the pipeline now, scoped to exactly these hotels
    # (see module docstring for why this always triggers rather than
    # deferring to an already-running run).
    dag_run_id: str | None = None
    queued = False
    detail: str | None = None
    try:
        result = airflow_client.trigger_dag_run(
            _EMBED_DAG_ID, conf={"hotel_ids": body.hotel_ids, "include_rooms": body.include_rooms}
        )
        dag_run_id = result.get("dag_run_id")
        queued = True
        # Otherwise a poller reading `GET /pipelines` right after this call
        # (the hotel-detail-page progress banner, or the Pipelines page
        # itself) can see a stale pre-trigger snapshot for up to 10s.
        invalidate_pipelines_cache()
    except airflow_client.AirflowUnavailable:
        detail = "airflow_unavailable"
    except airflow_client.AirflowError:
        detail = "airflow_request_failed"

    return ReembedHotelsResponse(
        cleared_hotels=cleared_hotels, cleared_rooms=cleared_rooms, dag_run_id=dag_run_id, queued=queued, detail=detail
    )

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from src.api.admin import admin_router
from src.api.routes import registry, router
from src.config import Settings, get_settings
from src.observability import install_api_error_logging

logger = logging.getLogger(__name__)

_CheckpointerPool = ConnectionPool[Connection[DictRow]]


def _require_checkpointer_database_url(settings: Settings) -> str:
    if not settings.checkpointer_database_url:
        raise RuntimeError(
            "checkpointer_backend='postgres' requires CHECKPOINTER_DATABASE_URL to be set "
            "(Supabase dashboard: Settings -> Database -> Connection string -> Session pooler)."
        )
    return settings.checkpointer_database_url


def _find_orphaned_thread_ids(pool: _CheckpointerPool, cutoff: datetime, limit: int) -> list[str]:
    """thread_ids whose newest checkpoint predates `cutoff`, oldest-need-first.

    Aggregates in SQL rather than through `PostgresSaver.list()`: that method
    is hardcoded `ORDER BY checkpoint_id DESC` (newest first) and hydrates a
    full checkpoint payload (plus joined blobs/writes) per row, so bounding it
    with `limit` returns the newest checkpoints -- the opposite of what an
    orphan sweep needs -- and does so expensively. This query reads only
    `thread_id` and the JSONB `ts` field actually written by every checkpoint
    (`checkpoints` schema, `langgraph-checkpoint-postgres`'s `.setup()`)."""
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT thread_id
            FROM checkpoints
            GROUP BY thread_id
            HAVING max((checkpoint ->> 'ts')::timestamptz) < %s
            LIMIT %s
            """,
            (cutoff, limit),
        )
        return [row["thread_id"] for row in cur.fetchall()]


def _sweep_orphaned_checkpoints(
    pool: _CheckpointerPool, checkpointer: PostgresSaver, max_age_seconds: float, limit: int = 1000
) -> None:
    """Deletes checkpoint threads whose newest checkpoint predates max_age_seconds.

    Event-triggered pruning (SessionRegistry.evict_expired/drop) only ever sees
    threads with a live in-memory session, so a thread written before a process
    restart has nothing left to trigger its cleanup -- this closes that gap at
    startup. `limit` bounds how many stale threads one sweep deletes, not which
    ones are visible -- see `_find_orphaned_thread_ids`."""
    cutoff = datetime.now(UTC) - timedelta(seconds=max_age_seconds)
    swept = 0
    for thread_id in _find_orphaned_thread_ids(pool, cutoff, limit):
        try:
            checkpointer.delete_thread(thread_id)
            swept += 1
        except Exception:
            logger.exception("Unable to sweep orphaned checkpoints for thread %s", thread_id)
    if swept:
        logger.info("Startup checkpoint sweep pruned %d orphaned thread(s)", swept)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger().setLevel(settings.log_level)
    print(f"Starting {settings.app_name} in {settings.app_env} mode")
    # State is per-session now (TripSession.pending_hotel_selection), so there is
    # no longer a process-global file whose leftover contents could poison the
    # first message of a new browser session — nothing to clear here.
    if settings.checkpointer_backend == "postgres":
        conn_string = _require_checkpointer_database_url(settings)
        # min/max_size kept small: this runs on a 1GB instance behind Supabase's
        # Supavisor pooler, which itself caps concurrent connections per
        # project -- a handful is plenty for one backend process.
        with _CheckpointerPool(
            conn_string,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            min_size=1,
            max_size=5,
            check=ConnectionPool.check_connection,
        ) as pool:
            pool.wait(timeout=10)
            checkpointer = PostgresSaver(pool)
            checkpointer.setup()
            _sweep_orphaned_checkpoints(pool, checkpointer, settings.session_ttl_seconds)
            registry.set_checkpointer(checkpointer)
            yield
    else:
        # No injection here: build_trip_agent's existing checkpointer=None
        # fallback (a fresh MemorySaver per session) already matches this
        # branch's behavior exactly -- nothing to change.
        yield
    print("Shutting down...")


app = FastAPI(
    title="AI20K Agent",
    description="AI Agent built with LangGraph",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
install_api_error_logging(app)


import time

# SSE endpoints: collecting the response body below would hold the ENTIRE
# stream until it closes — the client would receive nothing until the turn
# ends, killing SSE completely. Matched by exact path (not prefix) so no other
# endpoint's logging behaviour can change.
_STREAMING_PATHS = frozenset({"/api/v1/planner_chat/stream"})

@app.middleware("http")
async def log_api_io(request: Request, call_next):
    # Only log API routes
    if not request.url.path.startswith("/api/"):
        return await call_next(request)

    start_time = time.time()
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Read the request body for logging. starlette's _CachedRequest caches it
    # on the request object and replays it to the downstream app from that
    # cache, so no receive-stubbing is needed — and stubbing would actively
    # break StreamingResponse (its disconnect listener must observe a real
    # `http.disconnect` from the raw channel, never a replayed http.request).
    req_body = await request.body()

    req_str = req_body.decode('utf-8', errors='replace')
    print(f"\n[{current_time_str}] [API INPUT] {request.method} {request.url.path}\nPayload: {req_str}")

    if request.url.path in _STREAMING_PATHS:
        # Early exit BEFORE touching response.body_iterator: log input only and
        # hand the StreamingResponse straight through to the server.
        response = await call_next(request)
        print(f"[{current_time_str}] [API STREAM] {request.method} {request.url.path} (Status: {response.status_code}) — SSE passthrough, body not logged")
        return response

    response = await call_next(request)

    duration_ms = (time.time() - start_time) * 1000

    # Capture response body
    res_body = b""
    async for chunk in response.body_iterator:
        res_body += chunk

    res_str = res_body.decode('utf-8', errors='replace')
    print(f"[{current_time_str}] [API OUTPUT] {request.method} {request.url.path} (Status: {response.status_code}, Duration: {duration_ms:.2f}ms)\nPayload: {res_str[:2000]}" + ("..." if len(res_str) > 2000 else ""))

    from fastapi.responses import Response
    return Response(
        content=res_body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type
    )

@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}


from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router
from src.config import get_settings
from src.observability import install_api_error_logging


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
install_api_error_logging(app)


import time
from datetime import datetime

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


from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.api.routes import router
from src.cli.trip_builder_svc import _clear_pending_hotel_selection
from src.config import get_settings

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    print(f"Starting {settings.app_name} in {settings.app_env} mode")
    # A pending_hotel_selection.json left over from a previous run would make the
    # first message of a new browser session get misread as a hotel choice reply —
    # cleared once here (not per chat session, so one browser session starting
    # doesn't wipe another session's in-progress hotel choice).
    _clear_pending_hotel_selection()
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


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    """Basic web chat UI for the trip planner (calls POST /api/v1/planner_chat)."""
    return templates.TemplateResponse(request=request, name="chat.html")

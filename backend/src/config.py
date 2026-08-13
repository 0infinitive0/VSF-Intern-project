from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "V-OTA"
    app_env: Literal["development", "production", "test"] = "development"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: str = "http://localhost:3000,http://localhost:8082,http://localhost:5173"

    # Chat LLM & Providers
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    model_name: str = "gpt-4o-mini"
    llm_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    llm_provider: str = "ollama"
    llm_model: str = "llama3.1"
    llm_fast_model: str = "llama3.1"
    llm_api_key: str = ""
    llm_api_base: str = ""

    # Embedding Model
    embedding_provider: str = "ollama"
    embedding_model: str = "bge-m3"
    embedding_api_key: str = ""
    embedding_api_base: str = ""

    # Database
    database_url: str = "sqlite:///./data/app.db"

    # LangGraph checkpointer
    checkpointer_backend: Literal["memory", "postgres"] = Field(
        default="memory",
        description="LangGraph checkpoint backend for the FastAPI server's SessionRegistry. "
        "'postgres' persists graph state to a Postgres database and survives process restarts. "
        "CLI/script entry points (terminal_chat.py, poc_trip_planner.py) always use an "
        "in-process MemorySaver regardless of this flag -- they never run the FastAPI lifespan "
        "that builds and injects the Postgres checkpointer.",
    )
    checkpointer_database_url: str = Field(
        default="",
        description="Full Postgres connection string for the LangGraph checkpointer. Required "
        "when checkpointer_backend='postgres'. For Supabase, use the Supavisor pooler DSN from "
        "the dashboard (Settings -> Database -> Connection string -> Session pooler), e.g. "
        "postgresql://postgres.<project_ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres "
        "-- NOT the direct db.<project_ref>.supabase.co host, which is IPv6-only and unreachable "
        "from this project's Docker/EC2 deployment. Unrelated to database_url above.",
    )

    # Vector Store
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    ollama_url: str = "http://localhost:11434"
    supabase_url: str = ""
    supabase_service_key: str = ""

    # Session registry (Phase 3)
    session_ttl_seconds: int = Field(default=7200, ge=60, description="TTL per session in seconds (default 2h)")
    max_sessions: int = Field(default=200, ge=1, description="Hard cap on concurrent in-memory sessions")
    session_persistence_enabled: bool = Field(
        default=True,
        description="Persist chat sessions to Supabase and rehydrate them after in-memory eviction.",
    )
    debug_trip_plan_file: bool = Field(
        default=False,
        description="If True, writes trip plan JSON to debug/{session_id}/ for debugging (never global paths)",
    )

    # Supervisor router (Phase 3 of 260731-1508-supervisor-react-router-for-chat-turn)
    trip_supervisor_router: bool = Field(
        default=True,
        description="If True, an LLM supervisor proposes the chat-turn route before the "
        "deterministic regex fallback. Set to False to restore pure-regex routing without a "
        "deploy — the operational rollback for R1/R2/R3 in that plan.",
    )

    jailbreak_guard_mode: Literal["block", "log", "off"] = Field(
        default="block",
        description="How to handle high-confidence user jailbreak attempts before any LLM call.",
    )

    # Orchestration plane (260812-0927-langgraph-orchestration-state-patch-and-interrupts, Phase 5)
    orchestrator: Literal["graph", "legacy"] = Field(
        default="legacy",
        description="Which control plane handles a chat turn. 'legacy' is today's process_chat_turn "
        "cascade, frozen from Phase 5 on. 'graph' is the graph_v2 StateGraph (supervisor + worker "
        "nodes) built out across Phases 5-11. As of Phase 5, 'graph' dispatch only covers the "
        "POST /planner_chat fallback endpoint -- /planner_chat/stream (the frontend's default "
        "transport), /hotels/select, /hotels/change, and the other session endpoints still always "
        "run the legacy cascade regardless of this setting. Do not flip this in any environment the "
        "frontend actually talks to until that gap closes (streaming dispatch, or Phase 11 cutover).",
    )

    # Mapbox
    mapbox_access_token: str = ""

@lru_cache
def get_settings() -> Settings:
    return Settings()

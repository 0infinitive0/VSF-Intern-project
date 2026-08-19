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
    llm_reasoning_effort: Literal["minimal", "low", "medium", "high"] = Field(
        default="low",
        description="Effort level sent to OpenAI reasoning models (gpt-5/o1/o3/o4 family) "
        "via ChatOpenAI's `reasoning_effort` kwarg -- these models ignore `temperature` "
        "entirely, so this is their equivalent dial. The API's own default ('medium') was "
        "measured spending 76s and 1536 hidden reasoning tokens to answer a plain "
        "capabilities question in `qa_node`, 89% of that turn's 119s total latency. "
        "Non-reasoning models never receive this kwarg (see "
        "`_openai_model_supports_temperature` in `services/llm.py`).",
    )
    llm_use_responses_api: bool = Field(
        default=True,
        description="Route OpenAI calls through the Responses API instead of Chat "
        "Completions. On by default. It was opt-in while the block-shaped `content` "
        "it returns was still leaking through call sites that assumed a plain "
        "string; every one of those now reads through `services.llm.response_text`, "
        "and the streaming drain forwards only the agent's own text. Applies ONLY to "
        "the `openai` provider and ONLY to the reasoning family (gpt-5/o1/o3/o4) -- "
        "`gpt-4o-mini` answers the reasoning parameters this route implies with a "
        "400, and it is the model the eval judge hardcodes. Setting it to false is "
        "still the rollback, and it is an env change rather than a deploy.",
    )
    llm_reasoning_summary: Literal["off", "auto"] = Field(
        default="off",
        description="Ask OpenAI reasoning models to emit a summary of their own "
        "reasoning, streamed to the client as `reasoning` SSE frames. Requires "
        "`llm_use_responses_api` -- Chat Completions has no channel for it. Off by "
        "default because coverage is unpredictable: measured 2026-08-18, a model "
        "emits a summary only when it actually reasons, so the same step yields "
        "2000 characters for a hard request and nothing at all for a simple one, "
        "and a tool-calling step has no reasoning to summarize. Treat it as a layer "
        "over the graph's own facts, never as the only thing filling a UI slot.",
    )
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
    # OPTIONAL legacy fallback for JWT verification (src/auth/jwt_verifier.py).
    # Leave blank unless your Supabase project uses the old shared HS256 JWT
    # secret — verified 2026-08-14 that THIS project does not: it publishes a
    # real ES256 key at {SUPABASE_URL}/auth/v1/.well-known/jwks.json, so
    # jwt_verifier.py verifies via that JWKS endpoint by default (no secret
    # needed). If set, this HS256 secret is distinct from supabase_service_key
    # either way: it only ever verifies tokens locally, never sent to
    # Supabase, never used to construct a Postgres client.
    supabase_jwt_secret: str = ""

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

    qa_context_token_budget: int = Field(
        default=30_000,
        gt=0,
        description="Token ceiling on the transcript `qa_node` sends to the model, applied "
        "per LLM call inside its ReAct loop. `qa_node` is the only node handed the whole "
        "`messages` channel — every other prompt in the graph is built from a single "
        "message plus structured facts, so its size does not grow with the conversation. "
        "Sized for cost and latency, not for the context window: gpt-5-mini's window is "
        "far larger than any realistic session, but re-sending the full transcript on every "
        "ReAct hop bills the whole thing again each time. Older messages are dropped, never "
        "the newest; the tools can always re-read the real data.",
    )

    contract_enforcement_mode: Literal["strict", "log"] = Field(
        default="strict",
        description="How a node-contract violation is handled. 'strict' raises "
        "ContractViolation — the default so CI, which runs on defaults, refuses to merge "
        "a new violation. Production sets 'log': the violation is logged at ERROR and the "
        "turn continues, because a raise there costs the user the whole turn instead of "
        "just degrading one reply.",
    )

    # No `orchestrator` switch: the graph is the only control plane. The
    # legacy `process_chat_turn` cascade it used to select between is gone,
    # so a setting offering "legacy" could only ever have lied. Reintroduce
    # one when there is a second plane to actually switch to.

    # Auth (plan 260814-supabase-auth-and-per-user-history)
    auth_required: bool = Field(
        default=False,
        description="If True, session-scoped endpoints reject requests with no/invalid "
        "Supabase JWT. Kept False by default (mirrors session_persistence_enabled's "
        "rollout pattern) so the auth dependency can ship and be tested before traffic "
        "is actually rejected — flip only once the frontend is confirmed sending the "
        "Authorization header everywhere.",
    )

    # Mapbox
    mapbox_access_token: str = ""

    # VNPay (plan 260818-vnpay-payment-and-email-confirmation)
    vnpay_tmn_code: str = ""
    vnpay_hash_secret: str = ""
    vnpay_pay_url: str = Field(
        default="https://sandbox.vnpayment.vn/paymentv2/vpcpay.html",
        description="VNPay's hosted payment page. Sandbox by default -- production is "
        "https://vnpayment.vn/paymentv2/vpcpay.html, set only once real merchant "
        "credentials (not sandbox ones) are issued.",
    )
    vnpay_return_url: str = Field(
        default="",
        description="Frontend URL VNPay redirects the browser back to after payment -- "
        "e.g. https://<frontend-domain>/?payment_return=1 (see App.tsx's "
        "consumeVnpayReturn, mirroring oauth-redirect-error.ts). This redirect is "
        "UX-only and never trusted for confirmation -- see vnpay_ipn_url below.",
    )
    vnpay_ipn_url: str = Field(
        default="",
        description="Documentation only -- VNPay does not accept this as a request "
        "parameter for the payment-gateway API. The IPN URL is registered once in the "
        "VNPay merchant portal (sandbox or production) and must point at this backend's "
        "public /api/v1/payments/vnpay/ipn. Kept here so it is not just tribal knowledge.",
    )

    # Email (Resend -- plan 260818-vnpay-payment-and-email-confirmation)
    resend_api_key: str = ""
    resend_from_email: str = Field(
        default="onboarding@resend.dev",
        description="Resend's shared sandbox sender, usable with no domain verification "
        "for testing. Replace with a verified sender on your own domain before sending "
        "to real guests -- Resend rejects onboarding@resend.dev to recipients outside "
        "the account owner's own verified email in some configurations.",
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()

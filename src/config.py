from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "AI20K Agent"
    app_env: Literal["development", "production", "test"] = "development"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: str = "http://localhost:3000,http://localhost:8082"

    # LLM
    openai_api_key: str = ""
    model_name: str = "gpt-4o-mini"
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)

    # Database
    database_url: str = "sqlite:///./data/app.db"

    # Vector Store
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    ollama_url: str = "http://localhost:11434"
    supabase_url: str = ""
    supabase_service_key: str = ""

    @model_validator(mode="after")
    def _require_qdrant_api_key_in_production(self) -> "Settings":
        # Defense in depth, not the control — the control is
        # docker-compose.yml's QDRANT__SERVICE__API_KEY having no `:-`
        # fallback, which is what actually stops the server from starting
        # unauthenticated. This validator only catches the app itself being
        # misconfigured to run in production without a key; it can't make
        # any Qdrant server require one.
        if self.app_env == "production" and not self.qdrant_api_key:
            raise ValueError("QDRANT_API_KEY must be set when APP_ENV=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

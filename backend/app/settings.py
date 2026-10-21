"""Validated runtime configuration."""
from functools import lru_cache
from typing import Literal
from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "site-progress-agent"
    environment: str = Field(default="development", pattern="^(development|test|production)$")
    database_url: str = "postgresql+psycopg://progress:progress@127.0.0.1:5432/progress"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:4b"
    llm_provider: Literal["ollama", "groq", "openrouter"] = "ollama"
    groq_api_key: SecretStr | None = None
    groq_api_key_1: SecretStr | None = None
    groq_api_key_2: SecretStr | None = None
    groq_account_scopes_enabled: bool = False
    groq_model: str = "openai/gpt-oss-20b"
    openrouter_api_key: SecretStr | None = None
    # Deliberately unset: OpenRouter model IDs must be selected explicitly.
    openrouter_model: str | None = None
    orchestrator_provider: Literal["ollama", "groq", "openrouter"] | None = None
    orchestrator_model: str | None = None
    orchestrator_key_slot: Literal[0, 1, 2] = 0
    extraction_provider: Literal["ollama", "groq", "openrouter"] | None = None
    extraction_model: str | None = None
    extraction_key_slot: Literal[0, 1, 2] = 0
    selection_provider: Literal["ollama", "groq", "openrouter"] | None = None
    selection_model: str | None = None
    selection_key_slot: Literal[0, 1, 2] = 0
    report_model_timeout_seconds: int = Field(default=360, ge=30, le=900)
    conversation_model_timeout_seconds: int = Field(default=300, ge=30, le=900)
    ollama_api_key: SecretStr | None = None
    secret_key: str = Field(default="development-only-change-me", min_length=16)
    frontend_dist: str = "frontend/dist"
    upload_dir: str = "uploads"
    agent_execution_mode: Literal["graph"] = "graph"
    agent_hierarchy_enabled: bool = False
    orchestrator_model_assisted: bool = False

    @field_validator("orchestrator_key_slot", "extraction_key_slot", "selection_key_slot", mode="before")
    @classmethod
    def parse_key_slot(cls, value):
        # Environment variables are strings; Literal[int] does not coerce them.
        # Accept only the documented slots, never bools or arbitrary numbers.
        if isinstance(value, bool):
            raise ValueError("key slot must be 0, 1 or 2")
        return int(value) if isinstance(value, str) and value in {"0", "1", "2"} else value

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise RuntimeError(f"Invalid configuration. Fix these settings and restart: {details}") from exc

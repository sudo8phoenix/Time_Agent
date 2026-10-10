"""Validated runtime configuration."""
from functools import lru_cache
from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "site-progress-agent"
    environment: str = Field(default="development", pattern="^(development|test|production)$")
    database_url: str = "postgresql+psycopg://progress:progress@127.0.0.1:5432/progress"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:4b"
    conversation_model_timeout_seconds: int = Field(default=300, ge=30, le=900)
    ollama_api_key: SecretStr | None = None
    secret_key: str = Field(default="development-only-change-me", min_length=16)
    frontend_dist: str = "frontend/dist"
    upload_dir: str = "uploads"
    agent_execution_mode: str = Field(default="legacy", pattern="^(legacy|graph)$")

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise RuntimeError(f"Invalid configuration. Fix these settings and restart: {details}") from exc

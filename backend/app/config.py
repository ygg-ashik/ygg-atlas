from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://atlas:atlas@localhost:5433/ygg_atlas"

    # LLM provider: set exactly one key; anthropic wins if both are set.
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    agent_model: str = ""  # optional override; sensible per-provider default otherwise

    firebase_project_id: str = ""
    allowed_email_domain: str = "yougotagift.com"
    auth_disabled: bool = False
    # Fails closed: an unset ENVIRONMENT means production rules.
    environment: Literal["development", "test", "production"] = "production"
    # Comma-separated emails made admin at startup (idempotent). Spec §3.3.
    bootstrap_admins: str = ""
    # Web sessions are capped server-side from the token's auth_time. Spec §3.1.
    session_max_age_hours: int = 24

    # Source-specific config lives in each plugin's Settings
    # (app/sources/<id>/manifest.py)

    chat_daily_message_limit: int = 200
    agent_max_tool_rounds: int = 6
    max_input_chars: int = 4000

    atlas_mcp_token: str = ""
    # MCP calls run as this service user until per-user MCP auth (spec phase 4).
    mcp_service_email: str = "mcp-shared@atlas.internal"

    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def bootstrap_admin_list(self) -> list[str]:
        return [
            e.strip().lower() for e in self.bootstrap_admins.split(",") if e.strip()
        ]

    @model_validator(mode="after")
    def _fail_closed_outside_development(self) -> Self:
        if self.auth_disabled and self.environment == "production":
            msg = "AUTH_DISABLED=true needs ENVIRONMENT=development or test"
            raise ValueError(msg)
        if self.environment == "production" and not self.firebase_project_id:
            msg = "FIREBASE_PROJECT_ID is required when ENVIRONMENT=production"
            raise ValueError(msg)
        return self

    @property
    def llm_provider(self) -> str:
        return (
            "anthropic"
            if self.anthropic_api_key or not self.openai_api_key
            else "openai"
        )

    @property
    def resolved_agent_model(self) -> str:
        if self.agent_model:
            return self.agent_model
        return "claude-sonnet-4-6" if self.llm_provider == "anthropic" else "gpt-4.1"


@lru_cache
def get_settings() -> Settings:
    return Settings()

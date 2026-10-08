from functools import lru_cache

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

    # Source-specific config lives in each plugin's Settings
    # (app/sources/<id>/manifest.py)

    chat_daily_message_limit: int = 200
    agent_max_tool_rounds: int = 6
    max_input_chars: int = 4000

    atlas_mcp_token: str = ""

    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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

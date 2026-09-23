from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://atlas:atlas@localhost:5433/ygg_atlas"

    anthropic_api_key: str = ""
    agent_model: str = "claude-sonnet-4-6"

    firebase_project_id: str = ""
    allowed_email_domain: str = "yougotagift.com"
    auth_disabled: bool = False

    appdb_url: str = "postgresql+asyncpg://atlas:atlas@localhost:5433/ygg_atlas"
    ga4_property_id: str = ""

    chat_daily_message_limit: int = 200
    agent_max_tool_rounds: int = 6
    max_input_chars: int = 4000

    atlas_mcp_token: str = ""

    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

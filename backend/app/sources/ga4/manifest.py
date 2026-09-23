"""GA4 source: Google Analytics 4 Data API.

Enabled only when GA4_PROPERTY_ID is configured. Definitions are added once the
property + service-account credentials exist (until then this plugin ships the
connector only).
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.sources.base import SourcePlugin


class GA4Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ga4_property_id: str = ""


def _connector():
    from app.sources.ga4.connector import GA4Connector

    return GA4Connector()


SOURCE = SourcePlugin(
    id="ga4",
    name="Google Analytics 4",
    description="Web/app analytics from GA4 (sessions, users, engagement).",
    definitions_dir=Path(__file__).parent / "definitions",
    connector_factory=_connector,
    required_env=["GA4_PROPERTY_ID", "GOOGLE_APPLICATION_CREDENTIALS"],
    is_configured=lambda: bool(GA4Settings().ga4_property_id),
    allowed_tables=None,  # non-SQL source
)

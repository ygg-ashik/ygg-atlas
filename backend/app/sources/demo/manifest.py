"""Demo source: deterministic sample commerce data seeded into our own Postgres.

Stands in for the production ecom read replica until it is connected. Seed with
`uv run python scripts/seed_demo.py`. URL comes from APPDB_URL (defaults to the
ygg-atlas database).
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.sources.base import SourcePlugin, SQLSourceConnector


class DemoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    appdb_url: str = "postgresql+asyncpg://atlas:atlas@localhost:5433/ygg_atlas"


SOURCE = SourcePlugin(
    id="demo",
    name="Demo commerce data",
    description="Deterministic sample ecommerce data (orders, customers, checkout events) "
    "standing in for the production store until it is connected.",
    definitions_dir=Path(__file__).parent / "definitions",
    connector_factory=lambda: SQLSourceConnector(lambda: DemoSettings().appdb_url),
    required_env=["APPDB_URL"],
    allowed_tables={"demo_orders", "demo_customers", "demo_events"},
)

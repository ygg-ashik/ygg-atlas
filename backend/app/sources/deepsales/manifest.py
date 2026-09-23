"""DeepSales source: the B2B corporate-portfolio platform database.

Full data model: docs/data-models/deepsales.md (read it before touching definitions).

⚠ SECURITY: DEEPSALES_DB_URL_LIVE currently carries a superuser credential.
The connector enforces SELECT-only single statements, but the URL must be
swapped for a dedicated SELECT-only role (`ygg_atlas_ro`) as soon as the
DeepSales owner provides one.
"""

from pathlib import Path

import structlog
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.sources.base import SourcePlugin, SQLSourceConnector

logger = structlog.get_logger()


class DeepSalesSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    deepsales_db_url_live: str = ""

    @property
    def async_url(self) -> str:
        url = self.deepsales_db_url_live
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


def _connector():
    logger.warning(
        "deepsales.credential_warning",
        message="DEEPSALES_DB_URL_LIVE should be a SELECT-only role; "
        "connector-level enforcement is the interim guard",
    )
    return SQLSourceConnector(lambda: DeepSalesSettings().async_url)


SOURCE = SourcePlugin(
    id="deepsales",
    name="DeepSales portfolio",
    description="B2B corporate portfolio: account health, revenue (AED), CSM tasks, "
    "and the sales lead pipeline.",
    definitions_dir=Path(__file__).parent / "definitions",
    connector_factory=_connector,
    required_env=["DEEPSALES_DB_URL_LIVE"],
    is_configured=lambda: bool(DeepSalesSettings().deepsales_db_url_live),
    allowed_tables={
        "account_profiles",
        "corporate",
        "corporate_revenue_monthly",
        "tasks",
        "leads",
        "csm",
    },
)

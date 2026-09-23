"""Read-only connector to application databases (read replicas).

Safety: only single SELECT statements from the vetted registry are accepted,
parameters are always bound (never interpolated), and the connection string
should use a read-only database role.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from app.connectors.base import ConnectorError


def _assert_read_only(query: str) -> None:
    stripped = query.strip().rstrip(";").strip()
    if ";" in stripped:
        raise ConnectorError("Multiple statements are not allowed")
    first_word = stripped.split(None, 1)[0].upper() if stripped else ""
    if first_word not in {"SELECT", "WITH"}:
        raise ConnectorError("Only SELECT queries are allowed")


class AppDBConnector:
    key = "appdb"

    def __init__(self, url: str | None = None, engine: AsyncEngine | None = None):
        self._engine = engine
        self._url = url

    def _get_engine(self) -> AsyncEngine:
        if self._engine is None:
            self._engine = create_async_engine(
                self._url or get_settings().appdb_url, pool_pre_ping=True
            )
        return self._engine

    async def fetch_one(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        _assert_read_only(query)
        async with self._get_engine().connect() as conn:
            result = await conn.execute(text(query), params)
            row = result.mappings().first()
            return dict(row) if row is not None else None

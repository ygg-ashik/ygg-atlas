"""Source plugin contract.

A source plugin is a self-contained package under app/sources/<id>/ exposing
`SOURCE: SourcePlugin` from its manifest. It owns its configuration (reads only
its own env keys), its connector, and its semantic definitions. The atlas
kernel discovers plugins and never contains source-specific logic.

Connectors execute ONLY vetted queries from the plugin's definitions with bound
parameters — never model-generated SQL.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class ConnectorError(Exception):
    pass


class ConnectorNotConfiguredError(ConnectorError):
    pass


class Connector(Protocol):
    async def fetch_one(
        self, query: str, params: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def fetch_all(
        self, query: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]: ...


@dataclass
class SourcePlugin:
    """Everything the kernel needs to know about a data source."""

    id: str
    name: str
    description: str
    definitions_dir: Path
    connector_factory: Callable[[], Connector]
    required_env: list[str] = field(default_factory=list)
    is_configured: Callable[[], bool] = lambda: True
    # SQL sources: tables their queries may reference (load-time lint).
    # None => non-SQL source, lint skipped.
    allowed_tables: set[str] | None = None

    _connector: Connector | None = field(default=None, repr=False)

    def connector(self) -> Connector:
        if self._connector is None:
            self._connector = self.connector_factory()
        return self._connector

    def reset(self) -> None:
        """Test helper: drop the cached connector."""
        self._connector = None


def assert_read_only(query: str) -> None:
    stripped = query.strip().rstrip(";").strip()
    if ";" in stripped:
        raise ConnectorError("Multiple statements are not allowed")
    first_word = stripped.split(None, 1)[0].upper() if stripped else ""
    if first_word not in {"SELECT", "WITH"}:
        raise ConnectorError("Only SELECT queries are allowed")


class SQLSourceConnector:
    """Read-only SQL connector over a SQLAlchemy async engine.

    Use a SELECT-only database role for the URL; assert_read_only is a
    defense-in-depth guard, not the primary control.
    """

    def __init__(
        self, url_getter: Callable[[], str], engine: AsyncEngine | None = None
    ) -> None:
        self._url_getter = url_getter
        self._engine = engine

    def _get_engine(self) -> AsyncEngine:
        if self._engine is None:
            url = self._url_getter()
            if not url:
                raise ConnectorNotConfiguredError("Data source URL is not configured")
            # hide_parameters: driver errors carry no bound values (row-scope
            # values such as CSM names) into logs or the audit trail.
            self._engine = create_async_engine(
                url, pool_pre_ping=True, hide_parameters=True
            )
        return self._engine

    async def fetch_one(
        self, query: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        assert_read_only(query)
        async with self._get_engine().connect() as conn:
            result = await conn.execute(text(query), params)
            row = result.mappings().first()
            return dict(row) if row is not None else None

    async def fetch_all(
        self, query: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        assert_read_only(query)
        async with self._get_engine().connect() as conn:
            result = await conn.execute(text(query), params)
            return [dict(row) for row in result.mappings().all()]

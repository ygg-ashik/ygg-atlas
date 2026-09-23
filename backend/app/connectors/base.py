"""Connector contract: read-only access to a data source.

Connectors execute ONLY vetted queries from the atlas registry with bound
parameters. They never receive model-generated SQL.
"""

from typing import Any, Protocol


class ConnectorError(Exception):
    pass


class ConnectorNotConfigured(ConnectorError):
    pass


class Connector(Protocol):
    key: str

    async def fetch_one(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """Run a vetted parameterized query, return the first row as a dict."""
        ...


_connectors: dict[str, Connector] = {}


def register_connector(connector: Connector) -> None:
    _connectors[connector.key] = connector


def get_connector(key: str) -> Connector:
    if key not in _connectors:
        # Lazy default registration keeps import order simple.
        if key == "appdb":
            from app.connectors.appdb import AppDBConnector

            register_connector(AppDBConnector())
        elif key == "ga4":
            from app.connectors.ga4 import GA4Connector

            register_connector(GA4Connector())
        else:
            raise ConnectorNotConfigured(f"Unknown data source '{key}'")
    return _connectors[key]


def reset_connectors() -> None:
    """Test helper."""
    _connectors.clear()

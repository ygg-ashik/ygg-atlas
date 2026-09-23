import pytest

from app.connectors.appdb import AppDBConnector, _assert_read_only
from app.connectors.base import (
    ConnectorError,
    ConnectorNotConfigured,
    get_connector,
    reset_connectors,
)


def test_rejects_non_select():
    for query in (
        "DELETE FROM demo_orders",
        "UPDATE x SET a=1",
        "DROP TABLE demo_orders",
        "INSERT INTO x VALUES (1)",
    ):
        with pytest.raises(ConnectorError):
            _assert_read_only(query)


def test_rejects_multiple_statements():
    with pytest.raises(ConnectorError):
        _assert_read_only("SELECT 1; DELETE FROM demo_orders")


def test_allows_select_and_cte():
    _assert_read_only("SELECT 1")
    _assert_read_only("WITH t AS (SELECT 1) SELECT * FROM t")
    _assert_read_only("  select value from x;  ")


async def test_fetch_one_returns_row(db):
    connector = AppDBConnector()
    row = await connector.fetch_one("SELECT COUNT(*) AS value FROM demo_orders", {})
    assert row is not None
    assert row["value"] > 0


def test_unknown_connector_raises():
    reset_connectors()
    with pytest.raises(ConnectorNotConfigured):
        get_connector("bigquery")

import pytest

from app.sources import get_connector, get_plugins, reset_plugins
from app.sources.base import (
    ConnectorError,
    ConnectorNotConfigured,
    SQLSourceConnector,
    assert_read_only,
)


def test_rejects_non_select():
    for query in (
        "DELETE FROM demo_orders",
        "UPDATE x SET a=1",
        "DROP TABLE demo_orders",
        "INSERT INTO x VALUES (1)",
    ):
        with pytest.raises(ConnectorError):
            assert_read_only(query)


def test_rejects_multiple_statements():
    with pytest.raises(ConnectorError):
        assert_read_only("SELECT 1; DELETE FROM demo_orders")


def test_allows_select_and_cte():
    assert_read_only("SELECT 1")
    assert_read_only("WITH t AS (SELECT 1) SELECT * FROM t")
    assert_read_only("  select value from x;  ")


async def test_fetch_one_and_all(db):
    connector = get_connector("demo")
    row = await connector.fetch_one("SELECT COUNT(*) AS value FROM demo_orders", {})
    assert row is not None and row["value"] > 0

    rows = await connector.fetch_all(
        "SELECT channel AS label, COUNT(*) AS value FROM demo_orders "
        "GROUP BY channel ORDER BY value DESC LIMIT :limit",
        {"limit": 5},
    )
    assert {r["label"] for r in rows} == {"b2c", "b2b"}


def test_unconfigured_connector_raises():
    connector = SQLSourceConnector(lambda: "")
    with pytest.raises(ConnectorNotConfigured):
        connector._get_engine()


def test_unknown_source_raises(db):
    with pytest.raises(ConnectorNotConfigured):
        get_connector("bigquery")


def test_discovery_finds_demo_and_skips_unconfigured(monkeypatch, db):
    # GA4 has no GA4_PROPERTY_ID in the test env -> must be skipped.
    plugins = get_plugins()
    assert "demo" in plugins
    assert "ga4" not in plugins

    demo = plugins["demo"]
    assert demo.allowed_tables == {"demo_orders", "demo_customers", "demo_events"}

    # ga4 becomes discoverable once its env is present
    monkeypatch.setenv("GA4_PROPERTY_ID", "123456")
    reset_plugins()
    try:
        assert "ga4" in get_plugins()
    finally:
        monkeypatch.delenv("GA4_PROPERTY_ID")
        reset_plugins()

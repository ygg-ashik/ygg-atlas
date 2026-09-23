"""DeepSales plugin: definitions always lint; live queries only when configured."""

import pytest

from app.atlas.registry import AtlasRegistry
from app.sources.deepsales.manifest import SOURCE, DeepSalesSettings


def test_definitions_load_and_pass_table_lint():
    registry = AtlasRegistry(plugins={"deepsales": SOURCE})
    assert {
        "ds_total_accounts",
        "ds_at_risk_accounts",
        "ds_portfolio_revenue_ytd",
        "ds_revenue_aed",
        "ds_open_tasks",
        "ds_overdue_tasks",
        "ds_leads_created",
    } <= set(registry.metrics)
    assert "ds_lead_funnel" in registry.funnels

    snapshot_ids = {m.id for m in registry.metrics.values() if m.time_scope == "snapshot"}
    assert {"ds_total_accounts", "ds_at_risk_accounts", "ds_open_tasks"} <= snapshot_ids
    assert registry.metrics["ds_revenue_aed"].time_scope == "range"
    assert registry.metrics["ds_open_tasks"].breakdown_query is not None


def test_no_definition_selects_pii_contact_fields():
    registry = AtlasRegistry(plugins={"deepsales": SOURCE})
    forbidden = ("contact_email", "contact_phone", "email", "phone")
    for metric in registry.metrics.values():
        for query in filter(None, (metric.query, metric.breakdown_query)):
            for column in forbidden:
                # allow substrings inside other identifiers (e.g. email_domain not used)
                assert f" {column}" not in query.lower(), f"{metric.id} selects PII column {column}"


@pytest.mark.skipif(
    not DeepSalesSettings().deepsales_db_url_live, reason="DEEPSALES_DB_URL_LIVE not configured"
)
async def test_live_smoke_total_accounts():
    from app.atlas.tools import AtlasTools

    tools = AtlasTools(user_uid="test", registry=AtlasRegistry(plugins={"deepsales": SOURCE}))
    # monkeypatch-free: AtlasTools resolves the connector via global plugins;
    # ensure discovery ran with the live env present.
    from app.sources import get_plugins, reset_plugins

    reset_plugins()
    if "deepsales" not in get_plugins():
        pytest.skip("deepsales plugin not enabled")
    result = await tools.execute("query_metric", {"metric_id": "ds_total_accounts"})
    assert result.get("value", 0) > 0
    assert result["provenance"][0]["source"] == "deepsales"
    reset_plugins()

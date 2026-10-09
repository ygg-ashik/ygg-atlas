"""DeepSales plugin: definitions always lint; live queries only when configured."""

import pytest

from app.atlas import RowScope
from app.atlas.registry import AtlasRegistry
from app.atlas.scope import SCOPE_TOKEN, compile_scope
from app.sources import get_plugins, reset_plugins
from app.sources.base import assert_read_only
from app.sources.deepsales.manifest import SOURCE, DeepSalesSettings
from tests.fakes import make_tools


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

    snapshot_ids = {
        m.id for m in registry.metrics.values() if m.time_scope == "snapshot"
    }
    assert {"ds_total_accounts", "ds_at_risk_accounts", "ds_open_tasks"} <= snapshot_ids
    assert registry.metrics["ds_revenue_aed"].time_scope == "range"
    assert registry.metrics["ds_open_tasks"].breakdown_query is not None


def test_no_definition_selects_pii_contact_fields():
    registry = AtlasRegistry(plugins={"deepsales": SOURCE})
    forbidden = ("contact_email", "contact_phone", "email", "phone")
    queries = [
        (metric.id, query)
        for metric in registry.metrics.values()
        for query in (metric.query, metric.breakdown_query)
    ]
    queries += [
        (f"{funnel.id}/{step.id}", step.query)
        for funnel in registry.funnels.values()
        for step in funnel.steps
    ]
    queries += [
        (f"{entity.id} freshness", entity.freshness_query)
        for entity in registry.entities.values()
    ]
    for what, query in queries:
        if query is None:
            continue
        for column in forbidden:
            # allow substrings inside other identifiers (e.g. email_domain not used)
            assert f" {column}" not in query.lower(), (
                f"{what} selects PII column {column}"
            )


def test_deepsales_scoped_entities():
    """D3.13 with C1-C3: CSM-owned data is scoped by `csm` ($self = csm_name),
    leads by `owner` ($self = csm_email); every query carries {{scope}} and
    compiles to read-only SQL under a restricted scope."""
    registry = AtlasRegistry(plugins={"deepsales": SOURCE})
    catalog = registry.scope_catalog()
    assert [row[:4] for row in catalog] == [
        ("deepsales", "ds_account", "csm", "csm_name"),
        ("deepsales", "ds_lead", "owner", "csm_email"),
        ("deepsales", "ds_revenue", "csm", "csm_name"),
        ("deepsales", "ds_task", "csm", "csm_name"),
    ]
    assert all(row[4] for row in catalog), "every dimension is described"
    columns_by_entity = {
        "ds_account": {"csm": "csm_name"},
        "ds_lead": {"owner": "owner_email"},
        "ds_revenue": {"csm": "c.csm_name"},
        "ds_task": {"csm": "assignee_name"},
    }
    for entity_id, expected in columns_by_entity.items():
        entity = registry.entities[entity_id]
        columns = {d: v.column for d, v in entity.scope_dimensions.items()}
        assert columns == expected, entity_id
        queries = [q for m in entity.metrics for q in (m.query, m.breakdown_query)]
        queries += [s.query for f in entity.funnels for s in f.steps]
        queries.append(entity.freshness_query)
        scope: RowScope = ({next(iter(columns)): frozenset({"Jane Doe"})},)
        for query in filter(None, queries):
            assert SCOPE_TOKEN in query, f"{entity_id}: {query}"
            compiled = compile_scope(query, columns, scope)
            assert compiled.params == {"scope_0_0": "Jane Doe"}
            assert_read_only(compiled.sql)
            if entity_id == "ds_revenue":
                # U1/C3: revenue is scoped through the corporate's CSM.
                assert "JOIN corporate c ON c.id = m.corporate_id" in " ".join(
                    query.split()
                ), query
                assert "c.csm_name IN (:scope_0_0)" in compiled.sql


@pytest.mark.skipif(
    not DeepSalesSettings().deepsales_db_url_live,
    reason="DEEPSALES_DB_URL_LIVE not configured",
)
async def test_live_smoke_total_accounts():
    tools = make_tools(registry=AtlasRegistry(plugins={"deepsales": SOURCE}))
    # monkeypatch-free: AtlasTools resolves the connector via global plugins;
    # ensure discovery ran with the live env present.
    reset_plugins()
    if "deepsales" not in get_plugins():
        pytest.skip("deepsales plugin not enabled")
    result = await tools.execute("query_metric", {"metric_id": "ds_total_accounts"})
    assert result.get("value", 0) > 0
    assert result["provenance"][0]["source"] == "deepsales"
    reset_plugins()

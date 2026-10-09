"""Row scopes in the atlas kernel (D3.1, D3.7, D3.11): every query kind is compiled,
undeclared dimensions grant nothing, provenance names dimensions, audit records
the concrete scope.

Uses an ad-hoc registry over the real demo tables (a scoped copy of the order
definitions), so it does not depend on the shipped plugin YAML.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select
from structlog.testing import capture_logs

from app.atlas import AtlasCaller, AtlasRegistry, AtlasTools, RowScope
from app.atlas.scope import MAX_SCOPE_BINDS, UNDECLARED
from app.atlas.tools import POLICY_FAILED, AtlasAccessDeniedError
from app.models.audit import AtlasAuditLog
from app.sources.base import SourcePlugin
from tests.fakes import StaticPolicy, make_tools

B2C: RowScope = ({"channel": frozenset({"b2c"})},)
ORDERS = "demo/order/*"

ORDER_YAML = """
id: order
name: Orders
fields: {id: Order id, channel: Sales channel}
pii_fields: [customer_email]
freshness_query: >
  SELECT MAX(created_at) AS freshest FROM demo_orders WHERE TRUE {{scope}}
scope_dimensions:
  channel: {column: channel}
metrics:
  - id: revenue
    name: Total revenue
    unit: AED
    query: >
      SELECT COALESCE(SUM(amount), 0) AS value FROM demo_orders
      WHERE status = 'paid' AND created_at >= :start AND created_at <= :end {{scope}}
    breakdown_label_class: category
    breakdown_query: >
      SELECT channel AS label, SUM(amount) AS value FROM demo_orders
      WHERE status = 'paid' AND created_at >= :start AND created_at <= :end {{scope}}
      GROUP BY channel ORDER BY value DESC LIMIT :limit
funnels:
  - id: order_funnel
    name: Order funnel
    steps:
      - id: placed
        name: Placed
        query: >
          SELECT COUNT(*) AS value FROM demo_orders
          WHERE created_at >= :start AND created_at <= :end {{scope}}
      - id: paid
        name: Paid
        query: >
          SELECT COUNT(*) AS value FROM demo_orders WHERE status = 'paid'
          AND created_at >= :start AND created_at <= :end {{scope}}
"""

CUSTOMER_YAML = """
id: customer
name: Customers
metrics:
  - id: customers_total
    name: Customers
    time_scope: snapshot
    query: SELECT COUNT(*) AS value FROM demo_customers
"""


@pytest.fixture
def registry(tmp_path: Path) -> AtlasRegistry:
    (tmp_path / "order.yaml").write_text(ORDER_YAML)
    (tmp_path / "customer.yaml").write_text(CUSTOMER_YAML)
    plugin = SourcePlugin(
        id="demo",
        name="Demo",
        description="scoped test copy",
        definitions_dir=tmp_path,
        connector_factory=RecordingConnector,
        allowed_tables={"demo_orders", "demo_customers"},
    )
    return AtlasRegistry(plugins={"demo": plugin})


class RecordingConnector:
    """Captures every (sql, params) the kernel sends."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def fetch_one(self, query: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((query, params))
        return {"value": 1}

    async def fetch_all(
        self, query: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        self.calls.append((query, params))
        return [{"label": "b2c", "value": 1}]


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> RecordingConnector:
    connector = RecordingConnector()
    monkeypatch.setattr("app.atlas.tools.get_connector", lambda _source: connector)
    return connector


def _week() -> dict[str, str]:
    today = datetime.now(UTC).date()
    return {
        "start_date": (today - timedelta(days=7)).isoformat(),
        "end_date": (today - timedelta(days=1)).isoformat(),
    }


WEEK = {"start_date": "2026-01-01", "end_date": "2026-01-07"}


def _assert_scoped(sql: str, params: dict[str, Any]) -> None:
    assert "{{scope}}" not in sql
    assert ":scope_0_0" in sql
    assert params["scope_0_0"] == "b2c"


# ---- every query kind is compiled -----------------------------------------


async def test_every_query_kind_is_compiled(
    registry: AtlasRegistry, recorder: RecordingConnector
) -> None:
    tools = make_tools(registry=registry, row_scopes=[(ORDERS, B2C)])

    for tool, args in [
        ("query_metric", {"metric_id": "revenue", **WEEK}),
        ("metric_breakdown", {"metric_id": "revenue", "limit": 5, **WEEK}),
        ("funnel_analyze", {"funnel_id": "order_funnel", **WEEK}),
    ]:
        result = await tools.execute(tool, args)
        assert "error" not in result, result

    freshness = [c for c in recorder.calls if "MAX(created_at)" in c[0]]
    queries = [c for c in recorder.calls if "MAX(created_at)" not in c[0]]
    assert len(freshness) == 3  # one per tool's provenance
    assert len(queries) == 4  # metric, breakdown, two funnel steps
    for sql, params in recorder.calls:
        _assert_scoped(sql, params)
    for _sql, params in queries:
        assert {"start", "end"} <= params.keys()
    breakdown = next(p for s, p in queries if "GROUP BY" in s)
    assert breakdown["limit"] == 5


async def test_compare_periods_scopes_both_periods(
    registry: AtlasRegistry, recorder: RecordingConnector
) -> None:
    tools = make_tools(registry=registry, row_scopes=[(ORDERS, B2C)])
    result = await tools.execute(
        "compare_periods",
        {
            "metric_id": "revenue",
            "period_a_start": "2026-01-08",
            "period_a_end": "2026-01-14",
            "period_b_start": "2026-01-01",
            "period_b_end": "2026-01-07",
        },
    )
    assert "error" not in result
    metric_calls = [c for c in recorder.calls if "SUM(amount)" in c[0]]
    assert len(metric_calls) == 2
    for sql, params in recorder.calls:
        _assert_scoped(sql, params)


async def test_an_unrestricted_caller_compiles_to_true(
    registry: AtlasRegistry, recorder: RecordingConnector
) -> None:
    tools = make_tools(registry=registry)
    await tools.execute("query_metric", {"metric_id": "revenue", **WEEK})
    for sql, params in recorder.calls:
        assert "{{scope}}" not in sql
        assert "AND TRUE" in sql
        assert not any(k.startswith("scope_") for k in params)


# ---- real SQLite totals ----------------------------------------------------


async def test_scoped_revenue_is_3500_and_unscoped_10500(
    db: AsyncSession, registry: AtlasRegistry
) -> None:
    week = {"metric_id": "revenue", **_week()}
    scoped = make_tools(registry=registry, row_scopes=[(ORDERS, B2C)])
    unscoped = make_tools(registry=registry)

    assert (await scoped.execute("query_metric", week))["value"] == 3500.0
    assert (await unscoped.execute("query_metric", week))["value"] == 10500.0
    breakdown = await scoped.execute("metric_breakdown", week)
    assert [r["label"] for r in breakdown["rows"]] == ["b2c"]


async def test_two_alternatives_are_ored_on_sqlite(
    db: AsyncSession, registry: AtlasRegistry
) -> None:
    both: RowScope = (
        {"channel": frozenset({"b2c"})},
        {"channel": frozenset({"b2b"})},
    )
    tools = make_tools(registry=registry, row_scopes=[(ORDERS, both)])
    result = await tools.execute("query_metric", {"metric_id": "revenue", **_week()})
    assert result["value"] == 10500.0


# ---- undeclared, empty, failing and oversized scopes -----------------------


async def _audit_rows(db: AsyncSession, user_id: UUID) -> list[AtlasAuditLog]:
    result = await db.execute(
        select(AtlasAuditLog)
        .where(col(AtlasAuditLog.user_id) == user_id)
        .order_by(col(AtlasAuditLog.created_at))
    )
    return list(result.scalars().all())


async def test_an_undeclared_dimension_is_hidden_denied_and_audited(
    db: AsyncSession, registry: AtlasRegistry
) -> None:
    user_id = uuid4()
    region: RowScope = ({"region": frozenset({"gcc"})},)
    tools = make_tools(
        db=db, registry=registry, row_scopes=[(ORDERS, region)], user_id=user_id
    )

    listed = await tools.execute("list_metrics", {})
    ids = {m["id"] for s in listed["sources"] for m in s["metrics"]}
    assert ids == {"customers_total"}
    assert all(not s["funnels"] for s in listed["sources"])
    searched = await tools.execute("search_atlas", {"query": "revenue order"})
    assert ("metric", "revenue") not in {
        (r["kind"], r["id"]) for r in searched["results"]
    }
    described = await tools.execute("describe_entity", {"entity_id": "order"})
    assert "isn't available to you" in described["error"]
    described_row = (await _audit_rows(db, user_id))[-1]
    assert (described_row.tool, described_row.decision) == ("describe_entity", "deny")
    assert described_row.deny_reason == UNDECLARED
    result = await tools.execute("query_metric", {"metric_id": "revenue", **WEEK})

    assert "isn't available to you" in result["error"]
    assert "region" not in result["error"]  # business language, no internals
    row = (await _audit_rows(db, user_id))[-1]
    assert (row.tool, row.decision, row.success) == ("query_metric", "deny", False)
    assert row.deny_reason == UNDECLARED


async def test_a_scope_on_an_unscoped_entity_hides_it(
    registry: AtlasRegistry,
) -> None:
    tools = make_tools(registry=registry, row_scopes=[("demo/*", B2C)])
    listed = await tools.execute("list_metrics", {})
    ids = {m["id"] for s in listed["sources"] for m in s["metrics"]}
    assert ids == {"revenue"}
    denied = await tools.execute("query_metric", {"metric_id": "customers_total"})
    assert "isn't available to you" in denied["error"]


async def test_an_empty_row_scope_denies(
    registry: AtlasRegistry, recorder: RecordingConnector
) -> None:
    tools = make_tools(registry=registry, row_scopes=[(ORDERS, ())])
    result = await tools.execute("query_metric", {"metric_id": "revenue", **WEEK})
    assert "isn't available to you" in result["error"]
    assert recorder.calls == []
    listed = await tools.execute("list_metrics", {})
    assert {m["id"] for s in listed["sources"] for m in s["metrics"]} == {
        "customers_total"
    }


async def test_too_many_binds_deny_and_never_run_unscoped(
    db: AsyncSession, registry: AtlasRegistry, recorder: RecordingConnector
) -> None:
    user_id = uuid4()
    values = [frozenset({f"v{i}_{j}" for j in range(100)}) for i in range(11)]
    huge: RowScope = tuple({"channel": v} for v in values)
    assert sum(len(v) for v in values) > MAX_SCOPE_BINDS
    tools = make_tools(
        db=db, registry=registry, row_scopes=[(ORDERS, huge)], user_id=user_id
    )
    result = await tools.execute("query_metric", {"metric_id": "revenue", **WEEK})
    assert "isn't available to you" in result["error"]
    assert recorder.calls == []
    [row] = await _audit_rows(db, user_id)
    assert row.decision == "deny"
    assert "binds more than" in (row.deny_reason or "")


class _FailingScopePolicy(StaticPolicy):
    def row_scope(self, resource: str) -> RowScope | None:
        raise RuntimeError("scope store unreachable")


async def test_a_failing_row_scope_denies(
    db: AsyncSession, registry: AtlasRegistry, recorder: RecordingConnector
) -> None:
    user_id = uuid4()
    tools = AtlasTools(
        AtlasCaller(user_id=user_id, auth_method="test"),
        _FailingScopePolicy(),
        db=db,
        registry=registry,
    )
    result = await tools.execute("query_metric", {"metric_id": "revenue", **WEEK})
    assert "couldn't be checked against your access" in result["error"]
    assert recorder.calls == []
    assert (await tools.execute("list_metrics", {})) == {"sources": []}
    rows = await _audit_rows(db, user_id)
    assert (rows[0].decision, rows[0].deny_reason) == ("deny", POLICY_FAILED)


class _MalformedScopePolicy(StaticPolicy):
    def row_scope(self, resource: str) -> RowScope | None:
        return 42  # pyright: ignore[reportReturnType]  # a broken policy


async def test_a_malformed_row_scope_fails_closed(
    registry: AtlasRegistry, recorder: RecordingConnector
) -> None:
    tools = AtlasTools(
        AtlasCaller(user_id=uuid4(), auth_method="test"),
        _MalformedScopePolicy(),
        registry=registry,
    )
    result = await tools.execute("query_metric", {"metric_id": "revenue", **WEEK})
    assert "couldn't be checked against your access" in result["error"]
    assert recorder.calls == []


# ---- provenance and audit ---------------------------------------------------


async def test_provenance_names_dimensions_not_values(
    registry: AtlasRegistry, recorder: RecordingConnector
) -> None:
    scoped = make_tools(registry=registry, row_scopes=[(ORDERS, B2C)])
    for tool, args in [
        ("query_metric", {"metric_id": "revenue", **WEEK}),
        ("funnel_analyze", {"funnel_id": "order_funnel", **WEEK}),
    ]:
        [prov] = (await scoped.execute(tool, args))["provenance"]
        assert prov["scope"] == {"restricted": True, "dimensions": ["channel"]}
        assert "b2c" not in repr(prov)
        assert prov["masking"] is None

    unscoped = make_tools(registry=registry)
    [prov] = (await unscoped.execute("query_metric", {"metric_id": "revenue", **WEEK}))[
        "provenance"
    ]
    assert prov["scope"] == {"restricted": False, "dimensions": []}


async def test_audit_records_scope_and_masking(
    db: AsyncSession, registry: AtlasRegistry, recorder: RecordingConnector
) -> None:
    user_id = uuid4()
    tools = make_tools(
        db=db, registry=registry, row_scopes=[(ORDERS, B2C)], user_id=user_id
    )
    await tools.execute("list_metrics", {})
    await tools.execute("query_metric", {"metric_id": "revenue", **WEEK})
    await make_tools(db=db, registry=registry, user_id=user_id).execute(
        "query_metric", {"metric_id": "revenue", **WEEK}
    )

    listed, scoped, unscoped = await _audit_rows(db, user_id)
    assert listed.scope is None
    assert scoped.scope == {"restricted": True, "alternatives": [{"channel": ["b2c"]}]}
    assert scoped.masking is None
    assert unscoped.scope == {"restricted": False}


async def test_a_failing_scope_denies_describe_with_the_policy_reason(
    db: AsyncSession, registry: AtlasRegistry
) -> None:
    user_id = uuid4()
    tools = AtlasTools(
        AtlasCaller(user_id=user_id, auth_method="test"),
        _FailingScopePolicy(),
        db=db,
        registry=registry,
    )
    result = await tools.execute("describe_entity", {"entity_id": "order"})
    assert "isn't available to you" in result["error"]
    [row] = await _audit_rows(db, user_id)
    assert (row.decision, row.deny_reason) == ("deny", POLICY_FAILED)


async def test_a_failing_freshness_compile_is_logged_without_values(
    registry: AtlasRegistry,
    recorder: RecordingConnector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _broken(*_args: object) -> object:
        raise AtlasAccessDeniedError("Orders", "boom")

    tools = make_tools(registry=registry, row_scopes=[(ORDERS, B2C)])
    order = registry.entities["order"]
    with capture_logs() as logs:
        monkeypatch.setattr(tools, "_compile", _broken)
        freshness = await tools._freshness(order, B2C)
    assert freshness is None
    assert recorder.calls == []
    [event] = [e for e in logs if e["event"] == "atlas.freshness_scope_failed"]
    assert event["entity"] == "order"
    assert "b2c" not in repr(event)

"""Shipped demo definitions with row scopes (D3.13, C9): unscoped numbers are
unchanged, scopes narrow them, `orders_by_rep` breaks down by sales rep, and
every query of a scoped demo entity executes on SQLite once compiled."""

from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta

from app.atlas import RowScope
from app.atlas.models import EntityDef
from app.atlas.registry import get_registry
from app.atlas.scope import compile_scope
from app.sources import get_connector
from tests.fakes import make_tools

ORDERS = "demo/order/*"
CLEARED: frozenset[str] | None = None  # cleared for every label class


def _range(days: int) -> dict[str, str]:
    today = datetime.now(UTC).date()
    return {
        "start_date": (today - timedelta(days=days)).isoformat(),
        "end_date": (today - timedelta(days=1)).isoformat(),
    }


async def _value(db, metric_id: str, **kwargs) -> float:
    tools = make_tools(db=db, **kwargs)
    result = await tools.execute("query_metric", {"metric_id": metric_id, **_range(7)})
    assert "error" not in result, result
    return result["value"]


async def _breakdown(db, metric_id: str, **kwargs) -> dict[str, float]:
    tools = make_tools(db=db, **kwargs)
    result = await tools.execute(
        "metric_breakdown", {"metric_id": metric_id, "limit": 10, **_range(7)}
    )
    assert "error" not in result, result
    return {row["label"]: row["value"] for row in result["rows"]}


async def test_unscoped_demo_numbers_are_unchanged(db):
    assert await _value(db, "revenue") == 10500
    assert await _value(db, "orders_count") == 49
    assert await _value(db, "b2b_revenue") == 7000
    assert await _value(db, "new_customers") == 21

    tools = make_tools(db=db)
    funnel = await tools.execute(
        "funnel_analyze", {"funnel_id": "checkout_funnel", **_range(7)}
    )
    assert [s["count"] for s in funnel["steps"]] == [700, 420, 280, 175, 140]


async def test_channel_scope_gives_3500(db):
    b2c: RowScope = ({"channel": frozenset({"b2c"})},)
    assert await _value(db, "revenue", row_scopes=[(ORDERS, b2c)]) == 3500


async def test_orders_by_rep_breaks_down_by_rep(db):
    rows = await _breakdown(db, "orders_by_rep", clearances=CLEARED)
    assert rows == {"Aisha Khan": 21, "Omar Haddad": 14, "Lina Saab": 14}
    assert await _value(db, "orders_by_rep") == 49

    metric = get_registry().metrics["orders_by_rep"]
    assert metric.breakdown_label_class == "person_name"


async def test_sales_rep_scope(db):
    aisha: RowScope = ({"sales_rep": frozenset({"Aisha Khan"})},)
    scoped = [(ORDERS, aisha)]
    assert await _value(db, "orders_by_rep", row_scopes=scoped) == 21
    assert await _value(db, "revenue", row_scopes=scoped) == 2100
    rows = await _breakdown(db, "orders_by_rep", row_scopes=scoped)
    assert rows == {"Aisha Khan": 21}


async def test_segment_scope_on_customers(db):
    corporate: RowScope = ({"segment": frozenset({"corporate"})},)
    scoped = [("demo/customer/*", corporate)]
    assert await _value(db, "new_customers", row_scopes=scoped) == 7
    tools = make_tools(db=db, row_scopes=scoped)
    total = await tools.execute("query_metric", {"metric_id": "customers_total"})
    assert total["value"] == 10  # 10 seeded days x 1 corporate customer


def test_demo_scope_dimensions_are_declared():
    rows = [r for r in get_registry().scope_catalog() if r[0] == "demo"]
    assert [(r[1], r[2], r[3]) for r in rows] == [
        ("customer", "segment", None),
        ("order", "channel", None),
        ("order", "sales_rep", "rep_name"),
    ]
    assert get_registry().entities["checkout"].scope_dimensions == {}
    assert "sales_rep" in get_registry().entities["order"].fields


def _queries(entity: EntityDef) -> Iterator[tuple[str, str]]:
    for metric in entity.metrics:
        yield metric.id, metric.query
        if metric.breakdown_query:
            yield f"{metric.id} breakdown", metric.breakdown_query
    for funnel in entity.funnels:
        for step in funnel.steps:
            yield f"{funnel.id}/{step.id}", step.query
    if entity.freshness_query:
        yield "freshness", entity.freshness_query


async def test_every_scoped_demo_query_executes_on_sqlite(db):
    scoped = [
        e
        for e in get_registry().entities.values()
        if e.source == "demo" and e.scope_dimensions
    ]
    assert {e.id for e in scoped} == {"order", "customer"}
    connector = get_connector("demo")
    today = datetime.now(UTC).date()
    window = {
        "start": datetime.combine(today - timedelta(days=7), time.min, tzinfo=UTC),
        "end": datetime.combine(today, time.min, tzinfo=UTC),
        "limit": 10,
    }
    for entity in scoped:
        columns = {d: v.column for d, v in entity.scope_dimensions.items()}
        # Two alternatives, every dimension ANDed in the first: the widest shape.
        scope: RowScope = (
            {d: frozenset({"x", "y"}) for d in columns},
            {next(iter(columns)): frozenset({"z"})},
        )
        for what, sql in _queries(entity):
            compiled = compile_scope(sql, columns, scope)
            assert compiled.restricted, what
            params = {k: v for k, v in window.items() if f":{k}" in compiled.sql}
            rows = await connector.fetch_all(
                compiled.sql, {**params, **compiled.params}
            )
            # No row matches "x"/"y"/"z", so the predicate must filter everything:
            # breakdowns return no rows, aggregates 0 (COUNT/COALESCE) or NULL (MAX).
            if what.endswith("breakdown"):
                assert rows == [], what
            else:
                assert len(rows) == 1, what
                assert next(iter(rows[0].values())) in (0, None), what

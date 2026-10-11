from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlmodel import col, select

from app.atlas import AtlasCaller, AtlasTools, without_denial
from app.models.audit import AtlasAuditLog
from tests.fakes import StaticPolicy, make_tools


def _range(days: int) -> tuple[str, str]:
    today = datetime.now(UTC).date()
    return (today - timedelta(days=days)).isoformat(), (
        today - timedelta(days=1)
    ).isoformat()


async def test_list_metrics_grouped_by_source(db):
    tools = make_tools(db=db)
    result = await tools.execute("list_metrics", {})
    demo = next(s for s in result["sources"] if s["id"] == "demo")
    ids = [m["id"] for m in demo["metrics"]]
    assert "revenue" in ids
    assert any(f["id"] == "checkout_funnel" for f in demo["funnels"])
    revenue = next(m for m in demo["metrics"] if m["id"] == "revenue")
    assert revenue["has_breakdown"] is True
    assert revenue["time_scope"] == "range"


async def test_snapshot_metric_needs_no_dates(db):
    tools = make_tools(db=db)
    result = await tools.execute("query_metric", {"metric_id": "customers_total"})
    assert result["value"] == 30  # 10 seeded days x 3 customers
    assert "as_of" in result


async def test_range_metric_without_dates_is_guided_error(db):
    tools = make_tools(db=db)
    result = await tools.execute("query_metric", {"metric_id": "revenue"})
    assert "error" in result
    assert "start_date" in result["error"]


async def test_metric_breakdown(db):
    tools = make_tools(db=db)
    start, end = _range(7)
    result = await tools.execute(
        "metric_breakdown",
        {"metric_id": "revenue", "start_date": start, "end_date": end, "limit": 5},
    )
    rows = {r["label"]: r["value"] for r in result["rows"]}
    assert rows == {"b2b": 7000.0, "b2c": 3500.0}  # 7 days x (2x500 | 5x100)
    assert result["provenance"][0]["tool"] == "metric_breakdown"


async def test_breakdown_on_metric_without_view_errors(db):
    tools = make_tools(db=db)
    result = await tools.execute("metric_breakdown", {"metric_id": "aov"})
    assert "error" in result
    assert "no breakdown" in result["error"]


async def test_compare_periods_rejects_snapshot_metric(db):
    tools = make_tools(db=db)
    result = await tools.execute(
        "compare_periods",
        {
            "metric_id": "customers_total",
            "period_a_start": "2026-01-01",
            "period_a_end": "2026-01-07",
            "period_b_start": "2026-02-01",
            "period_b_end": "2026-02-07",
        },
    )
    assert "error" in result
    assert "snapshot" in result["error"]


async def test_query_metric_revenue(db):
    tools = make_tools(db=db)
    start, end = _range(7)
    result = await tools.execute(
        "query_metric", {"metric_id": "revenue", "start_date": start, "end_date": end}
    )
    # 7 days x (5x100 b2c + 2x500 b2b) = 7 x 1500
    assert result["value"] == 7 * 1500
    prov = result["provenance"][0]
    assert prov["metric_id"] == "revenue"
    assert prov["source"] == "demo"
    assert prov["freshness"] is not None


async def test_query_metric_unknown_id_is_guided_error(db):
    tools = make_tools(db=db)
    result = await tools.execute(
        "query_metric",
        {
            "metric_id": "churn_rate",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
    )
    assert "error" in result
    assert "clarifying question" in result["error"]


async def test_query_metric_invalid_dates(db):
    tools = make_tools(db=db)
    result = await tools.execute(
        "query_metric",
        {"metric_id": "revenue", "start_date": "not-a-date", "end_date": "2026-01-01"},
    )
    assert "error" in result

    result = await tools.execute(
        "query_metric",
        {"metric_id": "revenue", "start_date": "2026-02-01", "end_date": "2026-01-01"},
    )
    assert "error" in result


async def test_funnel_analyze(db):
    tools = make_tools(db=db)
    start, end = _range(7)
    result = await tools.execute(
        "funnel_analyze",
        {"funnel_id": "checkout_funnel", "start_date": start, "end_date": end},
    )
    counts = [s["count"] for s in result["steps"]]
    assert counts == [700, 420, 280, 175, 140]  # 7 days x [100, 60, 40, 25, 20]
    assert result["overall_conversion_pct"] == 20.0
    assert (
        result["biggest_drop"]["step"] == "Added to cart"
    )  # 100→60 is the -40% worst drop


async def test_compare_periods(db):
    tools = make_tools(db=db)
    today = datetime.now(UTC).date()
    result = await tools.execute(
        "compare_periods",
        {
            "metric_id": "orders_count",
            "period_a_start": (today - timedelta(days=3)).isoformat(),
            "period_a_end": (today - timedelta(days=1)).isoformat(),
            "period_b_start": (today - timedelta(days=6)).isoformat(),
            "period_b_end": (today - timedelta(days=4)).isoformat(),
        },
    )
    assert result["period_a"]["value"] == 21  # 3 days x 7 paid orders
    assert result["period_b"]["value"] == 21
    assert result["delta"] == 0
    assert result["delta_pct"] == 0


async def test_describe_entity(db):
    tools = make_tools(db=db)
    result = await tools.execute("describe_entity", {"entity_id": "order"})
    assert result["source"] == "demo"
    assert "customer_email" in result["pii_fields"]
    assert "revenue" in result["metrics"]


async def test_search_atlas_no_match_gives_clarify_hint(db):
    tools = make_tools(db=db)
    result = await tools.execute("search_atlas", {"query": "quarterly ebitda"})
    assert result["results"] == []
    assert "clarifying" in result["hint"].lower()


async def test_unknown_tool(db):
    tools = make_tools(db=db)
    result = await tools.execute("run_sql", {"sql": "SELECT 1"})
    assert "error" in result


async def test_every_execution_is_audited(db):
    user_id = uuid4()
    tools = make_tools(db=db, user_id=user_id)
    start, end = _range(2)
    await tools.execute(
        "query_metric", {"metric_id": "revenue", "start_date": start, "end_date": end}
    )
    await tools.execute(
        "query_metric", {"metric_id": "nope", "start_date": start, "end_date": end}
    )

    rows = (
        (
            await db.execute(
                select(AtlasAuditLog).where(col(AtlasAuditLog.user_id) == user_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {r.success for r in rows} == {True, False}
    assert all(r.tool == "query_metric" for r in rows)
    assert {r.decision for r in rows} == {"allow"}  # an unknown id is not a denial


class _UnreachablePolicy(StaticPolicy):
    """A policy whose evaluation fails: the "couldn't be checked" path."""

    def allows(self, resource: str) -> bool:
        raise RuntimeError("policy store unreachable")


async def test_denial_carries_a_denied_payload(db):
    tools = make_tools(db=db, allowed=("demo/order/*",))
    start, end = _range(7)
    result = await tools.execute(
        "funnel_analyze",
        {"funnel_id": "checkout_funnel", "start_date": start, "end_date": end},
    )
    assert result["denied"] == {
        "resource": "demo/checkout/checkout_funnel",
        "label": "Checkout funnel",
    }
    assert "isn't available to you" in result["error"]
    assert set(result) == {"error", "denied"}


async def test_policy_failure_has_no_denied_key(db):
    tools = AtlasTools(
        AtlasCaller(user_id=uuid4(), auth_method="test"), _UnreachablePolicy(), db=db
    )
    start, end = _range(7)
    result = await tools.execute(
        "query_metric", {"metric_id": "revenue", "start_date": start, "end_date": end}
    )
    assert "couldn't be checked" in result["error"]
    assert "denied" not in result


class _ReasonCrashPolicy(StaticPolicy):
    """Denies everything, then crashes while explaining why."""

    def deny_reason(self, resource: str) -> str:
        raise RuntimeError("policy store down")


async def test_a_crashed_deny_reason_offers_no_request_path(db):
    tools = AtlasTools(
        AtlasCaller(user_id=uuid4(), auth_method="test"),
        _ReasonCrashPolicy(allowed=()),
        db=db,
    )
    start, end = _range(7)
    result = await tools.execute(
        "query_metric", {"metric_id": "revenue", "start_date": start, "end_date": end}
    )
    assert "denied" not in result


async def test_other_failures_have_no_denied_key(db):
    tools = make_tools(db=db)
    result = await tools.execute("query_metric", {"metric_id": "nope"})
    assert "denied" not in result


async def test_denied_payload_holds_no_numbers(db):
    tools = make_tools(db=db, allowed=())
    start, end = _range(7)
    result = await tools.execute(
        "query_metric", {"metric_id": "revenue", "start_date": start, "end_date": end}
    )
    denied = result["denied"]
    assert set(denied) == {"resource", "label"}
    assert all(isinstance(v, str) for v in denied.values())
    assert not any(ch.isdigit() for v in denied.values() for ch in v)


async def test_a_scope_that_fails_to_compile_has_no_denied_key(db):
    # Allowed, but the row scope grants nothing here: not a request-access case.
    tools = make_tools(db=db, row_scopes=(("demo/order/*", ()),))
    start, end = _range(7)
    result = await tools.execute(
        "query_metric", {"metric_id": "revenue", "start_date": start, "end_date": end}
    )
    assert "error" in result
    assert "denied" not in result


def test_without_denial_strips_only_the_denial_payload():
    denied = {"resource": "demo/order/revenue", "label": "Total revenue"}
    result = {"error": "no", "denied": denied}
    assert without_denial(result) == {"error": "no"}
    assert result["denied"] == denied  # the input is not mutated
    assert without_denial({"value": 1.0}) == {"value": 1.0}

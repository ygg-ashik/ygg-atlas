from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.atlas.tools import AtlasTools
from app.models.audit import AtlasAuditLog


def _range(days: int) -> tuple[str, str]:
    today = datetime.now(UTC).date()
    return (today - timedelta(days=days)).isoformat(), (today - timedelta(days=1)).isoformat()


async def test_list_metrics(db):
    tools = AtlasTools(user_uid="u1", db=db)
    result = await tools.execute("list_metrics", {})
    ids = [m["id"] for m in result["metrics"]]
    assert "revenue" in ids
    assert any(f["id"] == "checkout_funnel" for f in result["funnels"])


async def test_query_metric_revenue(db):
    tools = AtlasTools(user_uid="u1", db=db)
    start, end = _range(7)
    result = await tools.execute(
        "query_metric", {"metric_id": "revenue", "start_date": start, "end_date": end}
    )
    # 7 days × (5×100 b2c + 2×500 b2b) = 7 × 1500
    assert result["value"] == 7 * 1500
    prov = result["provenance"][0]
    assert prov["metric_id"] == "revenue"
    assert prov["source"] == "appdb"
    assert prov["freshness"] is not None


async def test_query_metric_unknown_id_is_guided_error(db):
    tools = AtlasTools(user_uid="u1", db=db)
    result = await tools.execute(
        "query_metric",
        {"metric_id": "churn_rate", "start_date": "2026-01-01", "end_date": "2026-01-31"},
    )
    assert "error" in result
    assert "clarifying question" in result["error"]


async def test_query_metric_invalid_dates(db):
    tools = AtlasTools(user_uid="u1", db=db)
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
    tools = AtlasTools(user_uid="u1", db=db)
    start, end = _range(7)
    result = await tools.execute(
        "funnel_analyze", {"funnel_id": "checkout_funnel", "start_date": start, "end_date": end}
    )
    counts = [s["count"] for s in result["steps"]]
    assert counts == [700, 420, 280, 175, 140]  # 7 days × [100, 60, 40, 25, 20]
    assert result["overall_conversion_pct"] == 20.0
    assert result["biggest_drop"]["step"] == "Added to cart"  # 100→60 is the −40% worst drop


async def test_compare_periods(db):
    tools = AtlasTools(user_uid="u1", db=db)
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
    assert result["period_a"]["value"] == 21  # 3 days × 7 paid orders
    assert result["period_b"]["value"] == 21
    assert result["delta"] == 0
    assert result["delta_pct"] == 0


async def test_describe_entity(db):
    tools = AtlasTools(user_uid="u1", db=db)
    result = await tools.execute("describe_entity", {"entity_id": "order"})
    assert result["source"] == "appdb"
    assert "customer_email" in result["pii_fields"]
    assert "revenue" in result["metrics"]


async def test_search_atlas_no_match_gives_clarify_hint(db):
    tools = AtlasTools(user_uid="u1", db=db)
    result = await tools.execute("search_atlas", {"query": "quarterly ebitda"})
    assert result["results"] == []
    assert "clarifying" in result["hint"].lower()


async def test_unknown_tool(db):
    tools = AtlasTools(user_uid="u1", db=db)
    result = await tools.execute("run_sql", {"sql": "SELECT 1"})
    assert "error" in result


async def test_every_execution_is_audited(db):
    tools = AtlasTools(user_uid="auditme", db=db)
    start, end = _range(2)
    await tools.execute(
        "query_metric", {"metric_id": "revenue", "start_date": start, "end_date": end}
    )
    await tools.execute("query_metric", {"metric_id": "nope", "start_date": start, "end_date": end})

    rows = (
        (await db.execute(select(AtlasAuditLog).where(AtlasAuditLog.user_uid == "auditme")))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {r.success for r in rows} == {True, False}
    assert all(r.tool == "query_metric" for r in rows)

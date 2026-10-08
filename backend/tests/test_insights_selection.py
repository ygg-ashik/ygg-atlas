from datetime import date

from app.atlas.models import MetricDef
from app.insights.selection import (
    PREFERRED_KPIS,
    kpi_from_compare,
    kpi_from_query,
    pick_breakdown_metric,
    pick_kpi_metrics,
    windows,
)


def _m(
    id_: str, scope: str = "range", breakdown: str | None = None, good: str = "up"
) -> MetricDef:
    return MetricDef(
        id=id_,
        name=id_.title(),
        unit="AED",
        time_scope=scope,
        query="select 1",
        breakdown_query=breakdown,
        good_direction=good,
        source="demo",
        entity="order",
    )


PROV = {
    "tool": "compare_periods",
    "source": "demo",
    "metric_id": "revenue",
    "metric_name": "Revenue",
    "freshness": None,
    "executed_at": "t",
}


def test_windows_are_full_days_ending_yesterday() -> None:
    cur, prev = windows(days=7, today=date(2026, 10, 8))
    assert cur == ("2026-10-01", "2026-10-07")
    assert prev == ("2026-09-24", "2026-09-30")


def test_pick_kpi_metrics_prefers_known_order_and_caps_at_four() -> None:
    ids = ["aov", "revenue", "orders_count", "b2b_revenue", "new_customers", "zzz"]
    metrics = {i: _m(i) for i in ids}
    picked = pick_kpi_metrics(metrics)
    assert [m.id for m in picked] == ["revenue", "orders_count", "aov", "b2b_revenue"]


def test_pick_kpi_metrics_fills_from_other_metrics() -> None:
    metrics = {
        "leads_total": _m("leads_total"),
        "tasks_open": _m("tasks_open", "snapshot"),
    }
    assert [m.id for m in pick_kpi_metrics(metrics)] == ["leads_total", "tasks_open"]


def test_pick_breakdown_metric_needs_a_breakdown_query() -> None:
    metrics = {
        "orders_count": _m("orders_count"),
        "revenue": _m("revenue", breakdown="q"),
    }
    picked = pick_breakdown_metric(metrics)
    assert picked is not None
    assert picked.id == "revenue"
    assert pick_breakdown_metric({"x": _m("x")}) is None


def test_kpi_from_compare() -> None:
    result = {
        "name": "Revenue",
        "unit": "AED",
        "period_a": {"value": 120.0},
        "period_b": {"value": 100.0},
        "delta_pct": 20.0,
        "provenance": [PROV],
    }
    assert kpi_from_compare(_m("revenue"), result) == {
        "metric_id": "revenue",
        "name": "Revenue",
        "unit": "AED",
        "value": 120.0,
        "previous": 100.0,
        "delta_pct": 20.0,
        "good_direction": "up",
        "provenance": PROV,
    }


def test_kpi_from_query_snapshot_has_no_previous() -> None:
    result = {"name": "Tasks Open", "unit": "", "value": 7.0, "provenance": [PROV]}
    kpi = kpi_from_query(_m("tasks_open", scope="snapshot", good="down"), result)
    assert kpi is not None
    assert kpi["previous"] is None
    assert kpi["delta_pct"] is None
    assert kpi["good_direction"] == "down"


def test_error_results_are_skipped() -> None:
    assert kpi_from_compare(_m("revenue"), {"error": "x"}) is None
    assert kpi_from_query(_m("revenue"), {"error": "x"}) is None


def test_preferred_list_is_stable() -> None:
    assert PREFERRED_KPIS[:4] == ["revenue", "orders_count", "aov", "b2b_revenue"]

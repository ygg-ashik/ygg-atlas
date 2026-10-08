"""Which governed metrics and windows the overview shows. Pure: no I/O, no SQL."""

from datetime import date, timedelta
from typing import Any

from app.atlas.models import MetricDef

PREFERRED_KPIS = ["revenue", "orders_count", "aov", "b2b_revenue", "new_customers"]
MAX_KPIS = 4
ALLOWED_DAYS = (7, 30, 90)

Window = tuple[str, str]


def windows(days: int, today: date) -> tuple[Window, Window]:
    """Current = last `days` full UTC days ending yesterday; previous precedes it."""
    end = today - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    current = (start.isoformat(), end.isoformat())
    previous = (prev_start.isoformat(), prev_end.isoformat())
    return current, previous


def _ordered(metrics: dict[str, MetricDef]) -> list[MetricDef]:
    preferred = [metrics[mid] for mid in PREFERRED_KPIS if mid in metrics]
    rest = [metrics[mid] for mid in sorted(metrics) if mid not in PREFERRED_KPIS]
    return preferred + rest


def pick_kpi_metrics(metrics: dict[str, MetricDef]) -> list[MetricDef]:
    """Preferred headline metrics first, then the rest by id, capped at MAX_KPIS."""
    return _ordered(metrics)[:MAX_KPIS]


def pick_breakdown_metric(metrics: dict[str, MetricDef]) -> MetricDef | None:
    """The first metric (in KPI order) that has a governed top-N view."""
    return next((m for m in _ordered(metrics) if m.breakdown_query), None)


def first_provenance(result: dict[str, Any]) -> dict[str, Any] | None:
    """The leading provenance record of an atlas tool result, if any."""
    prov: list[dict[str, Any]] = result.get("provenance") or []
    return prov[0] if prov else None


def _kpi(
    metric: MetricDef, result: dict[str, Any], value: float, previous: float | None
) -> dict[str, Any]:
    return {
        "metric_id": metric.id,
        "name": result.get("name", metric.name),
        "unit": result.get("unit", metric.unit),
        "value": value,
        "previous": previous,
        "delta_pct": result.get("delta_pct"),
        "good_direction": metric.good_direction,
        "provenance": first_provenance(result),
    }


def kpi_from_compare(
    metric: MetricDef, result: dict[str, Any]
) -> dict[str, Any] | None:
    """Shape a compare_periods result as a KPI; None for errors or no provenance."""
    if "error" in result or first_provenance(result) is None:
        return None
    current = result["period_a"]["value"]
    previous = result["period_b"]["value"]
    return _kpi(metric, result, current, previous)


def kpi_from_query(metric: MetricDef, result: dict[str, Any]) -> dict[str, Any] | None:
    """Shape a query_metric (snapshot) result as a KPI with no comparison."""
    if "error" in result or first_provenance(result) is None:
        return None
    return _kpi(metric, result, result["value"], None)

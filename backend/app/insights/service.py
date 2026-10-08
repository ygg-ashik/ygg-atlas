"""Insights use cases: the catalog and the dashboard overview.

All numbers come from AtlasTools (audited, provenance-bearing). No SQL, no FastAPI.
"""

from datetime import date
from typing import Any

import structlog

from app.atlas import AtlasTools
from app.atlas.models import MetricDef
from app.insights.schemas import MetricsCatalog, Overview
from app.insights.selection import (
    Window,
    first_provenance,
    kpi_from_compare,
    kpi_from_query,
    pick_breakdown_metric,
    pick_kpi_metrics,
    windows,
)

logger = structlog.get_logger()

BREAKDOWN_LIMIT = 5


class InsightsService:
    """Read-only views over governed metrics. Every number goes through AtlasTools."""

    def __init__(self, tools: AtlasTools) -> None:
        self._tools = tools

    async def catalog(self) -> MetricsCatalog:
        """Every governed metric and funnel, grouped by source."""
        result = await self._tools.execute("list_metrics", {})
        return MetricsCatalog.model_validate(result)

    async def overview(self, days: int, today: date) -> Overview:
        """Headline KPIs vs the previous window, plus one top-N breakdown."""
        current, previous = windows(days, today)
        metrics = self._tools.registry.metrics
        kpis: list[dict[str, Any]] = []
        for metric in pick_kpi_metrics(metrics):
            kpi = await self._kpi(metric, current, previous)
            if kpi is None:
                logger.warning("insights.kpi_skipped", metric_id=metric.id)
            else:
                kpis.append(kpi)
        breakdown = await self._breakdown(pick_breakdown_metric(metrics), current)
        return Overview.model_validate(
            {
                "days": days,
                "start_date": current[0],
                "end_date": current[1],
                "kpis": kpis,
                "breakdown": breakdown,
            }
        )

    async def _kpi(
        self, metric: MetricDef, current: Window, previous: Window
    ) -> dict[str, Any] | None:
        if metric.time_scope == "snapshot":
            result = await self._tools.execute("query_metric", {"metric_id": metric.id})
            return kpi_from_query(metric, result)
        result = await self._tools.execute(
            "compare_periods",
            {
                "metric_id": metric.id,
                "period_a_start": current[0],
                "period_a_end": current[1],
                "period_b_start": previous[0],
                "period_b_end": previous[1],
            },
        )
        return kpi_from_compare(metric, result)

    async def _breakdown(
        self, metric: MetricDef | None, current: Window
    ) -> dict[str, Any] | None:
        if metric is None:
            return None
        args: dict[str, Any] = {"metric_id": metric.id, "limit": BREAKDOWN_LIMIT}
        if metric.time_scope == "range":
            args |= {"start_date": current[0], "end_date": current[1]}
        result = await self._tools.execute("metric_breakdown", args)
        provenance = first_provenance(result)
        if "error" in result or provenance is None:
            logger.warning("insights.breakdown_skipped", metric_id=metric.id)
            return None
        return {
            "metric_id": metric.id,
            "name": result["name"],
            "unit": result["unit"],
            "rows": result["rows"],
            "provenance": provenance,
        }

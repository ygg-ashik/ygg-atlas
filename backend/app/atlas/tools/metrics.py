"""Metric tools: query_metric, metric_breakdown (masked) and compare_periods.

Each authorises the metric before any query, compiles the caller's row scope
into it, and returns the number with its provenance.
"""

from datetime import UTC, datetime
from typing import Any

from app.atlas.models import EntityDef, MetricDef
from app.atlas.policy import metric_resource
from app.atlas.provenance import build_provenance, provenance_scope
from app.atlas.scope import RowScope
from app.atlas.tools.dates import range_params
from app.atlas.tools.door import AtlasDoor, Compile, Freshness, connector
from app.atlas.tools.errors import AtlasToolError
from app.atlas.tools.labels import LabelMasker

DEFAULT_BREAKDOWN_LIMIT = 10
MAX_BREAKDOWN_LIMIT = 50


class MetricTools:
    """Governed metric values for one caller."""

    def __init__(
        self,
        door: AtlasDoor,
        masker: LabelMasker,
        *,
        compile_sql: Compile,
        freshness: Freshness,
    ) -> None:
        self._door = door
        self._masker = masker
        self._compile = compile_sql
        self._freshness = freshness

    async def query_metric(
        self, metric_id: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        metric, entity, scope = self._get_metric(metric_id)
        params = self._metric_params(metric, start_date, end_date)
        compiled = self._compile(metric.query, entity, scope, metric.name)
        row = await connector(metric.source).fetch_one(
            compiled.sql, params | compiled.params
        )
        value = row.get("value") if row else None
        result: dict[str, Any] = {
            "metric_id": metric.id,
            "name": metric.name,
            "unit": metric.unit,
            "value": float(value) if value is not None else 0.0,
            "provenance": await self._provenance("query_metric", metric, entity, scope),
        }
        if metric.time_scope == "snapshot":
            result["as_of"] = datetime.now(UTC).isoformat()
        else:
            result["start_date"] = start_date
            result["end_date"] = end_date
        return result

    async def metric_breakdown(
        self,
        metric_id: str,
        limit: int = DEFAULT_BREAKDOWN_LIMIT,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        metric, entity, scope = self._get_metric(metric_id)
        if not metric.breakdown_query:
            raise AtlasToolError(f"Metric '{metric_id}' has no breakdown view.")
        limit = max(1, min(int(limit), MAX_BREAKDOWN_LIMIT))
        params = self._metric_params(metric, start_date, end_date) | {"limit": limit}
        compiled = self._compile(metric.breakdown_query, entity, scope, metric.name)
        fetched = await connector(metric.source).fetch_all(
            compiled.sql, params | compiled.params
        )
        rows = [
            {
                "label": r.get("label"),
                "value": float(r["value"]) if r.get("value") is not None else 0.0,
            }
            for r in fetched
        ]
        result, masking = self._masker.mask(rows, metric.breakdown_label_class)
        return {
            "metric_id": metric.id,
            "name": metric.name,
            "unit": metric.unit,
            **result,
            "provenance": await self._provenance(
                "metric_breakdown", metric, entity, scope, masking
            ),
        }

    async def compare_periods(
        self,
        metric_id: str,
        period_a_start: str,
        period_a_end: str,
        period_b_start: str,
        period_b_end: str,
    ) -> dict[str, Any]:
        metric, _, _ = self._get_metric(metric_id)
        if metric.time_scope == "snapshot":
            raise AtlasToolError(
                f"Metric '{metric_id}' is a point-in-time snapshot and cannot be "
                "compared across periods."
            )
        a = await self.query_metric(metric_id, period_a_start, period_a_end)
        b = await self.query_metric(metric_id, period_b_start, period_b_end)
        delta = a["value"] - b["value"]
        pct = (delta / b["value"] * 100) if b["value"] else None
        return {
            "metric_id": metric_id,
            "name": a["name"],
            "unit": a["unit"],
            "period_a": {
                "start": period_a_start,
                "end": period_a_end,
                "value": a["value"],
            },
            "period_b": {
                "start": period_b_start,
                "end": period_b_end,
                "value": b["value"],
            },
            "delta": delta,
            "delta_pct": round(pct, 1) if pct is not None else None,
            "provenance": a["provenance"],
        }

    def _get_metric(
        self, metric_id: str
    ) -> tuple[MetricDef, EntityDef | None, RowScope | None]:
        registry = self._door.registry
        metric = registry.metrics.get(metric_id)
        if metric is None:
            raise AtlasToolError(
                f"No metric '{metric_id}' in the atlas. Use list_metrics or "
                "search_atlas; if nothing fits, ask the user a clarifying question "
                "instead of guessing."
            )
        entity = registry.entities.get(metric.entity)
        scope = self._door.authorize(metric_resource(metric), metric.name, entity)
        return metric, entity, scope

    def _metric_params(
        self, metric: MetricDef, start_date: str | None, end_date: str | None
    ) -> dict[str, Any]:
        if metric.time_scope == "snapshot":
            return {}
        if not start_date or not end_date:
            raise AtlasToolError(
                f"Metric '{metric.id}' needs start_date and end_date (ISO dates). "
                "Resolve relative dates yourself and retry."
            )
        return range_params(start_date, end_date)

    async def _provenance(
        self,
        tool: str,
        metric: MetricDef,
        entity: EntityDef | None,
        scope: RowScope | None,
        masking: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            build_provenance(
                tool,
                metric.source,
                metric_id=metric.id,
                metric_name=metric.name,
                freshness=await self._freshness(entity, scope),
                scope=provenance_scope(scope),
                masking=masking,
            )
        ]

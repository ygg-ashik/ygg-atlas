"""The six atlas tools — the ONLY way agents access business data.

Consumed in-process by the chat agent and exposed verbatim over MCP.
Every execution is audited. Every numeric result carries provenance.
"""

import time
from datetime import UTC, date, datetime
from datetime import time as dt_time
from typing import Any
from uuid import UUID

import structlog

from app.atlas.models import MetricDef
from app.atlas.provenance import build_provenance
from app.atlas.registry import AtlasRegistry, get_registry
from app.connectors import ConnectorError, ConnectorNotConfigured, get_connector
from app.models.audit import AtlasAuditLog

logger = structlog.get_logger()


class AtlasToolError(Exception):
    """User-visible tool failure; the agent should relay/explain it, not retry blindly."""


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise AtlasToolError(f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}") from None


def _range_params(start: str, end: str) -> dict[str, Any]:
    """Inclusive UTC datetime bounds: [start 00:00:00, end 23:59:59.999999]."""
    start_d = _parse_date(start, "start_date")
    end_d = _parse_date(end, "end_date")
    if end_d < start_d:
        raise AtlasToolError("end_date must be on or after start_date")
    return {
        "start": datetime.combine(start_d, dt_time.min, tzinfo=UTC),
        "end": datetime.combine(end_d, dt_time.max, tzinfo=UTC),
    }


class AtlasTools:
    """Tool executor bound to a user (for audit). db_session is the ygg-atlas DB."""

    def __init__(
        self,
        user_uid: str,
        surface: str = "chat",
        session_id: UUID | None = None,
        db=None,
        registry: AtlasRegistry | None = None,
    ):
        self.user_uid = user_uid
        self.surface = surface
        self.session_id = session_id
        self.db = db
        self.registry = registry or get_registry()

    async def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch + audit. Returns a JSON-safe dict; errors become {'error': ...}."""
        handlers = {
            "list_metrics": self.list_metrics,
            "query_metric": self.query_metric,
            "describe_entity": self.describe_entity,
            "funnel_analyze": self.funnel_analyze,
            "compare_periods": self.compare_periods,
            "search_atlas": self.search_atlas,
        }
        if tool not in handlers:
            return {"error": f"Unknown tool '{tool}'"}

        started = time.monotonic()
        success, error = True, None
        try:
            result = await handlers[tool](**arguments)
        except (AtlasToolError, ConnectorNotConfigured, ConnectorError) as exc:
            success, error = False, str(exc)
            result = {"error": str(exc)}
        except TypeError as exc:
            success, error = False, f"Invalid arguments: {exc}"
            result = {"error": f"Invalid arguments: {exc}"}
        except Exception as exc:  # unexpected — log loudly, keep the answer honest
            logger.exception("atlas.tool_failed", tool=tool)
            success, error = False, str(exc)
            result = {"error": f"Internal error executing {tool}"}

        await self._audit(tool, arguments, success, error, int((time.monotonic() - started) * 1000))
        return result

    async def _audit(self, tool, arguments, success, error, duration_ms) -> None:
        if self.db is None:
            return
        self.db.add(
            AtlasAuditLog(
                user_uid=self.user_uid,
                session_id=self.session_id,
                surface=self.surface,
                tool=tool,
                arguments=arguments,
                success=success,
                error=error,
                duration_ms=duration_ms,
            )
        )
        await self.db.commit()

    # ---- the six tools -------------------------------------------------

    async def list_metrics(self) -> dict:
        return {
            "metrics": [
                {
                    "id": m.id,
                    "name": m.name,
                    "description": m.description,
                    "entity": m.entity,
                    "source": m.source,
                    "unit": m.unit,
                }
                for m in self.registry.metrics.values()
            ],
            "funnels": [
                {"id": f.id, "name": f.name, "description": f.description, "entity": f.entity}
                for f in self.registry.funnels.values()
            ],
        }

    async def query_metric(self, metric_id: str, start_date: str, end_date: str) -> dict:
        metric = self.registry.metrics.get(metric_id)
        if metric is None:
            raise AtlasToolError(
                f"No metric '{metric_id}' in the atlas. Use list_metrics or search_atlas; "
                "if nothing fits, ask the user a clarifying question instead of guessing."
            )
        params = _range_params(start_date, end_date)
        row = await get_connector(metric.source).fetch_one(metric.query, params)
        value = row.get("value") if row else None
        return {
            "metric_id": metric.id,
            "name": metric.name,
            "unit": metric.unit,
            "start_date": start_date,
            "end_date": end_date,
            "value": float(value) if value is not None else 0.0,
            "provenance": await self._metric_provenance("query_metric", metric),
        }

    async def describe_entity(self, entity_id: str) -> dict:
        entity = self.registry.entities.get(entity_id)
        if entity is None:
            raise AtlasToolError(f"No entity '{entity_id}' in the atlas. Use search_atlas.")
        return {
            "id": entity.id,
            "name": entity.name,
            "description": entity.description,
            "source": entity.source,
            "fields": entity.fields,
            "pii_fields": entity.pii_fields,
            "metrics": [m.id for m in entity.metrics],
            "funnels": [f.id for f in entity.funnels],
        }

    async def funnel_analyze(self, funnel_id: str, start_date: str, end_date: str) -> dict:
        funnel = self.registry.funnels.get(funnel_id)
        if funnel is None:
            raise AtlasToolError(f"No funnel '{funnel_id}' in the atlas. Use list_metrics.")
        params = _range_params(start_date, end_date)
        connector = get_connector(funnel.source)

        steps: list[dict] = []
        prev_count: float | None = None
        worst = {"step": None, "drop_pct": 0.0}
        for step in funnel.steps:
            row = await connector.fetch_one(step.query, params)
            count = float(row.get("value", 0) if row else 0)
            conversion = (count / prev_count * 100) if prev_count else None
            if conversion is not None:
                drop = 100 - conversion
                if drop > worst["drop_pct"]:
                    worst = {"step": step.name, "drop_pct": round(drop, 1)}
            steps.append(
                {
                    "id": step.id,
                    "name": step.name,
                    "count": count,
                    "conversion_from_previous_pct": round(conversion, 1)
                    if conversion is not None
                    else None,
                }
            )
            prev_count = count if count > 0 else prev_count

        overall = (
            round(steps[-1]["count"] / steps[0]["count"] * 100, 1)
            if steps and steps[0]["count"]
            else None
        )
        entity = self.registry.entities.get(funnel.entity)
        return {
            "funnel_id": funnel.id,
            "name": funnel.name,
            "start_date": start_date,
            "end_date": end_date,
            "steps": steps,
            "overall_conversion_pct": overall,
            "biggest_drop": worst,
            "provenance": [
                build_provenance(
                    "funnel_analyze",
                    funnel.source,
                    metric_id=funnel.id,
                    metric_name=funnel.name,
                    freshness=await self._freshness(entity) if entity else None,
                )
            ],
        }

    async def compare_periods(
        self,
        metric_id: str,
        period_a_start: str,
        period_a_end: str,
        period_b_start: str,
        period_b_end: str,
    ) -> dict:
        a = await self.query_metric(metric_id, period_a_start, period_a_end)
        b = await self.query_metric(metric_id, period_b_start, period_b_end)
        delta = a["value"] - b["value"]
        pct = (delta / b["value"] * 100) if b["value"] else None
        return {
            "metric_id": metric_id,
            "name": a["name"],
            "unit": a["unit"],
            "period_a": {"start": period_a_start, "end": period_a_end, "value": a["value"]},
            "period_b": {"start": period_b_start, "end": period_b_end, "value": b["value"]},
            "delta": delta,
            "delta_pct": round(pct, 1) if pct is not None else None,
            "provenance": a["provenance"],
        }

    async def search_atlas(self, query: str) -> dict:
        results = self.registry.search(query)
        return {
            "results": results,
            "hint": (
                "Nothing matched. Ask the user a clarifying question — do not guess or fabricate."
                if not results
                else None
            ),
        }

    # ---- helpers -------------------------------------------------------

    async def _metric_provenance(self, tool: str, metric: MetricDef) -> list[dict]:
        entity = self.registry.entities.get(metric.entity)
        return [
            build_provenance(
                tool,
                metric.source,
                metric_id=metric.id,
                metric_name=metric.name,
                freshness=await self._freshness(entity) if entity else None,
            )
        ]

    async def _freshness(self, entity) -> str | None:
        if not entity or not entity.freshness_query:
            return None
        try:
            row = await get_connector(entity.source).fetch_one(entity.freshness_query, {})
            if row:
                value = next(iter(row.values()), None)
                return str(value) if value is not None else None
        except ConnectorError:
            return None
        return None


ATLAS_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "list_metrics",
        "description": "List every governed metric and funnel in the atlas, with descriptions. "
        "Call this first when unsure what data exists.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_metric",
        "description": "Get the value of a governed metric for a UTC date range (inclusive). "
        "The only sanctioned way to obtain a business number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_id": {"type": "string", "description": "Metric id from list_metrics"},
                "start_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
            },
            "required": ["metric_id", "start_date", "end_date"],
        },
    },
    {
        "name": "describe_entity",
        "description": "Describe an atlas entity: fields, PII flags, its metrics and funnels.",
        "input_schema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string"}},
            "required": ["entity_id"],
        },
    },
    {
        "name": "funnel_analyze",
        "description": "Analyze a governed funnel over a date range: step counts, step conversion, "
        "overall conversion, and the biggest drop-off point.",
        "input_schema": {
            "type": "object",
            "properties": {
                "funnel_id": {"type": "string"},
                "start_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
            },
            "required": ["funnel_id", "start_date", "end_date"],
        },
    },
    {
        "name": "compare_periods",
        "description": "Compare a metric between two date ranges (e.g. this month vs last month). "
        "Returns both values, absolute delta, and percent change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_id": {"type": "string"},
                "period_a_start": {"type": "string"},
                "period_a_end": {"type": "string"},
                "period_b_start": {"type": "string"},
                "period_b_end": {"type": "string"},
            },
            "required": [
                "metric_id",
                "period_a_start",
                "period_a_end",
                "period_b_start",
                "period_b_end",
            ],
        },
    },
    {
        "name": "search_atlas",
        "description": "Keyword-search the atlas for entities, metrics, and funnels "
        "matching a topic.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
]

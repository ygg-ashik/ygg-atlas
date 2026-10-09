"""The seven atlas tools — the ONLY way agents access business data.

Consumed in-process by the chat agent and exposed verbatim over MCP.
Every execution is audited. Every numeric result carries provenance.
"""

import time
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as dt_time
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.atlas.models import EntityDef, FunnelDef, MetricDef
from app.atlas.policy import (
    AtlasCaller,
    ResourcePolicy,
    entity_resource,
    funnel_resource,
    metric_resource,
)
from app.atlas.provenance import build_provenance
from app.atlas.registry import AtlasRegistry, get_registry
from app.models.audit import AtlasAuditLog
from app.sources import ConnectorError, ConnectorNotConfiguredError, get_connector

logger = structlog.get_logger()

SEARCH_LIMIT = 10
ALLOW = "allow"
DENY = "deny"
MAX_DENY_REASON = 200
POLICY_FAILED = "the access check failed"
UNKNOWN_TOOL = "unknown tool"

DEFAULT_BREAKDOWN_LIMIT = 10
MAX_BREAKDOWN_LIMIT = 50


class AtlasToolError(Exception):
    """User-visible tool failure.

    The agent should relay/explain it, not retry blindly.
    """


class AtlasAccessDeniedError(AtlasToolError):
    """The caller's policy denies a governed resource (spec §6, point 2)."""

    def __init__(self, label: str, reason: str, message: str | None = None) -> None:
        super().__init__(
            message
            or f"{label} isn't available to you. Ask an atlas admin if you need it."
        )
        self.reason = reason


class AtlasPolicyError(AtlasToolError):
    """The caller's policy could not be evaluated; fail closed (spec §12)."""


@dataclass(frozen=True, slots=True)
class _Outcome:
    success: bool = True
    error: str | None = None
    decision: str = ALLOW
    deny_reason: str | None = None


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise AtlasToolError(
            f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}"
        ) from None


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
    """Tool executor for one caller: filtered by their policy, audited per call."""

    def __init__(
        self,
        caller: AtlasCaller,
        policy: ResourcePolicy,
        db: AsyncSession | None = None,
        registry: AtlasRegistry | None = None,
    ) -> None:
        self.caller = caller
        self._policy = policy
        self.db = db
        self._registry = registry

    @property
    def registry(self) -> AtlasRegistry:
        return self._registry if self._registry is not None else get_registry()

    def visible_metrics(self) -> dict[str, MetricDef]:
        """Metrics this caller may see (spec §6, enforcement point 1)."""
        return {
            mid: m
            for mid, m in self.registry.metrics.items()
            if self._visible(metric_resource(m))
        }

    def visible_funnels(self) -> dict[str, FunnelDef]:
        return {
            fid: f
            for fid, f in self.registry.funnels.items()
            if self._visible(funnel_resource(f))
        }

    async def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch + audit. Returns a JSON-safe dict; errors become {'error': ...}."""
        handlers = {
            "list_metrics": self.list_metrics,
            "query_metric": self.query_metric,
            "metric_breakdown": self.metric_breakdown,
            "describe_entity": self.describe_entity,
            "funnel_analyze": self.funnel_analyze,
            "compare_periods": self.compare_periods,
            "search_atlas": self.search_atlas,
        }
        started = time.monotonic()
        if tool not in handlers:
            error = f"Unknown tool '{tool}'"
            await self._audit(
                tool, arguments, _Outcome(False, error, DENY, UNKNOWN_TOOL), 0
            )
            return {"error": error}

        outcome = _Outcome()
        try:
            result = await handlers[tool](**arguments)
        except AtlasAccessDeniedError as exc:
            outcome = _Outcome(False, str(exc), DENY, exc.reason[:MAX_DENY_REASON])
            result = {"error": str(exc)}
        except (AtlasToolError, ConnectorNotConfiguredError, ConnectorError) as exc:
            outcome = _Outcome(False, str(exc))
            result = {"error": str(exc)}
        except TypeError as exc:
            outcome = _Outcome(False, f"Invalid arguments: {exc}")
            result = {"error": f"Invalid arguments: {exc}"}
        except Exception as exc:  # unexpected — log loudly, keep the answer honest
            logger.exception("atlas.tool_failed", tool=tool)
            outcome = _Outcome(False, str(exc))
            result = {"error": f"Internal error executing {tool}"}

        elapsed_ms = int((time.monotonic() - started) * 1000)
        await self._audit(tool, arguments, outcome, elapsed_ms)
        return result

    async def _audit(
        self,
        tool: str,
        arguments: dict[str, Any],
        outcome: _Outcome,
        duration_ms: int,
    ) -> None:
        if self.db is None:
            return
        self.db.add(
            AtlasAuditLog(
                user_uid=str(self.caller.user_id),
                user_id=self.caller.user_id,
                auth_method=self.caller.auth_method,
                session_id=self.caller.session_id,
                surface=self.caller.surface,
                tool=tool,
                arguments=arguments,
                success=outcome.success,
                error=outcome.error,
                duration_ms=duration_ms,
                decision=outcome.decision,
                deny_reason=outcome.deny_reason,
                token_id=self.caller.token_id,
                client_id=self.caller.client_id,
            )
        )
        await self.db.commit()

    def _allowed(self, resource: str) -> bool:
        """The one call into the policy; any failure becomes AtlasPolicyError."""
        try:
            return self._policy.allows(resource)
        except Exception as exc:
            raise AtlasPolicyError(POLICY_FAILED) from exc

    def _visible(self, resource: str) -> bool:
        """Discovery check (point 1): a failing policy hides the item."""
        try:
            return self._allowed(resource)
        except AtlasPolicyError:
            logger.exception("atlas.policy_error", resource=resource)
            return False

    def _denied(self, resource: str, label: str) -> AtlasAccessDeniedError:
        try:
            reason = self._policy.deny_reason(resource)
        except Exception:
            logger.exception("atlas.policy_error", resource=resource)
            reason = POLICY_FAILED
        return AtlasAccessDeniedError(label, reason)

    def _authorize(self, resource: str, label: str) -> None:
        """Execution check (point 2): a failing policy denies.

        A policy-evaluation failure is not a real denial — it gets its own
        honest message, never "isn't available to you" (that claims the
        policy was consulted and said no).
        """
        try:
            allowed = self._allowed(resource)
        except AtlasPolicyError as exc:
            logger.exception("atlas.policy_error", resource=resource)
            raise AtlasAccessDeniedError(
                label,
                POLICY_FAILED,
                message=(
                    f"{label} couldn't be checked against your access right "
                    "now. Try again shortly."
                ),
            ) from exc
        if not allowed:
            raise self._denied(resource, label)

    def _entity_visible(self, entity: EntityDef) -> bool:
        return (
            self._visible(entity_resource(entity))
            or any(self._visible(metric_resource(m)) for m in entity.metrics)
            or any(self._visible(funnel_resource(f)) for f in entity.funnels)
        )

    # ---- helpers ---------------------------------------------------------

    def _get_metric(self, metric_id: str) -> MetricDef:
        metric = self.registry.metrics.get(metric_id)
        if metric is None:
            raise AtlasToolError(
                f"No metric '{metric_id}' in the atlas. Use list_metrics or "
                "search_atlas; if nothing fits, ask the user a clarifying question "
                "instead of guessing."
            )
        self._authorize(metric_resource(metric), metric.name)
        return metric

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
        return _range_params(start_date, end_date)

    async def _freshness(self, entity: EntityDef | None) -> str | None:
        if not entity or not entity.freshness_query:
            return None
        try:
            row = await get_connector(entity.source).fetch_one(
                entity.freshness_query, {}
            )
            if row:
                value = next(iter(row.values()), None)
                return str(value) if value is not None else None
        except ConnectorError:
            return None
        return None

    async def _metric_provenance(
        self, tool: str, metric: MetricDef
    ) -> list[dict[str, Any]]:
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

    # ---- the seven tools -------------------------------------------------

    async def list_metrics(self) -> dict[str, Any]:
        sources: dict[str, dict[str, Any]] = {}
        for plugin in self.registry.plugins.values():
            sources[plugin.id] = {
                "id": plugin.id,
                "name": plugin.name,
                "description": plugin.description,
                "metrics": [],
                "funnels": [],
            }
        for m in self.visible_metrics().values():
            sources[m.source]["metrics"].append(
                {
                    "id": m.id,
                    "name": m.name,
                    "description": m.description,
                    "entity": m.entity,
                    "unit": m.unit,
                    "time_scope": m.time_scope,
                    "has_breakdown": m.breakdown_query is not None,
                }
            )
        for f in self.visible_funnels().values():
            sources[f.source]["funnels"].append(
                {
                    "id": f.id,
                    "name": f.name,
                    "description": f.description,
                    "entity": f.entity,
                }
            )
        return {
            "sources": [s for s in sources.values() if s["metrics"] or s["funnels"]]
        }

    async def query_metric(
        self, metric_id: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        metric = self._get_metric(metric_id)
        params = self._metric_params(metric, start_date, end_date)
        row = await get_connector(metric.source).fetch_one(metric.query, params)
        value = row.get("value") if row else None
        result = {
            "metric_id": metric.id,
            "name": metric.name,
            "unit": metric.unit,
            "value": float(value) if value is not None else 0.0,
            "provenance": await self._metric_provenance("query_metric", metric),
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
        metric = self._get_metric(metric_id)
        if not metric.breakdown_query:
            raise AtlasToolError(f"Metric '{metric_id}' has no breakdown view.")
        limit = max(1, min(int(limit), MAX_BREAKDOWN_LIMIT))
        params = self._metric_params(metric, start_date, end_date) | {"limit": limit}
        rows = await get_connector(metric.source).fetch_all(
            metric.breakdown_query, params
        )
        return {
            "metric_id": metric.id,
            "name": metric.name,
            "unit": metric.unit,
            "rows": [
                {
                    "label": r.get("label"),
                    "value": float(r["value"]) if r.get("value") is not None else 0.0,
                }
                for r in rows
            ],
            "provenance": await self._metric_provenance("metric_breakdown", metric),
        }

    async def describe_entity(self, entity_id: str) -> dict[str, Any]:
        entity = self.registry.entities.get(entity_id)
        if entity is None:
            raise AtlasToolError(
                f"No entity '{entity_id}' in the atlas. Use search_atlas."
            )
        if not self._entity_visible(entity):
            raise self._denied(entity_resource(entity), entity.name)
        metrics, funnels = self.visible_metrics(), self.visible_funnels()
        return {
            "id": entity.id,
            "name": entity.name,
            "description": entity.description,
            "source": entity.source,
            "fields": entity.fields,
            "pii_fields": entity.pii_fields,
            "metrics": [m.id for m in entity.metrics if m.id in metrics],
            "funnels": [f.id for f in entity.funnels if f.id in funnels],
        }

    async def funnel_analyze(
        self, funnel_id: str, start_date: str, end_date: str
    ) -> dict[str, Any]:
        funnel = self.registry.funnels.get(funnel_id)
        if funnel is None:
            raise AtlasToolError(
                f"No funnel '{funnel_id}' in the atlas. Use list_metrics."
            )
        self._authorize(funnel_resource(funnel), funnel.name)
        params = _range_params(start_date, end_date)
        connector = get_connector(funnel.source)

        steps: list[dict[str, Any]] = []
        prev_count: float | None = None
        worst: dict[str, Any] = {"step": None, "drop_pct": 0.0}
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
    ) -> dict[str, Any]:
        metric = self._get_metric(metric_id)
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

    async def search_atlas(self, query: str) -> dict[str, Any]:
        entities = {
            e.id for e in self.registry.entities.values() if self._entity_visible(e)
        }
        visible: dict[str, Collection[str]] = {
            "metric": self.visible_metrics().keys(),
            "funnel": self.visible_funnels().keys(),
            "entity": entities,
        }
        results = self.registry.search(
            query,
            limit=SEARCH_LIMIT,
            visible=lambda kind, id_: id_ in visible.get(kind, ()),
        )
        return {
            "results": results,
            "hint": (
                "Nothing matched. Ask the user a clarifying question — do not guess "
                "or fabricate."
                if not results
                else None
            ),
        }


_DATE_PROPS = {
    "start_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
    "end_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
}

ATLAS_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_metrics",
        "description": "List every governed metric and funnel in the atlas, grouped "
        "by data source, with descriptions. Call this first when unsure what data "
        "exists.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_metric",
        "description": "Get the value of a governed metric. Range metrics require "
        "start_date/end_date (inclusive UTC); snapshot metrics ('as of now') take no "
        "dates. The only sanctioned way to obtain a business number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_id": {
                    "type": "string",
                    "description": "Metric id from list_metrics",
                },
                **_DATE_PROPS,
            },
            "required": ["metric_id"],
        },
    },
    {
        "name": "metric_breakdown",
        "description": "Top-N breakdown of a metric (e.g. top accounts by revenue, "
        "tasks per CSM). Only for metrics where list_metrics shows "
        "has_breakdown=true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_id": {"type": "string"},
                "limit": {
                    "type": "integer",
                    "description": "Rows to return (default 10, max 50)",
                },
                **_DATE_PROPS,
            },
            "required": ["metric_id"],
        },
    },
    {
        "name": "describe_entity",
        "description": "Describe an atlas entity: fields, PII flags, its metrics and "
        "funnels.",
        "input_schema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string"}},
            "required": ["entity_id"],
        },
    },
    {
        "name": "funnel_analyze",
        "description": "Analyze a governed funnel over a date range: step counts, "
        "step conversion, overall conversion, and the biggest drop-off point.",
        "input_schema": {
            "type": "object",
            "properties": {"funnel_id": {"type": "string"}, **_DATE_PROPS},
            "required": ["funnel_id", "start_date", "end_date"],
        },
    },
    {
        "name": "compare_periods",
        "description": "Compare a range metric between two date ranges (e.g. this "
        "month vs last month). Returns both values, absolute delta, and percent "
        "change.",
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

"""The seven atlas tools — the ONLY way agents access business data.

Consumed in-process by the chat agent and exposed verbatim over MCP.
Every execution is audited. Every numeric result carries provenance.
"""

import time
from collections.abc import Awaitable, Callable, Collection
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as dt_time
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.atlas.masking import CATEGORY, CLEARANCE_FOR_CLASS, MaskMode, mask_breakdown
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
from app.atlas.scope import (
    SCOPE_TOKEN,
    UNDECLARED,
    CompiledScope,
    RowScope,
    ScopeCompileError,
    compile_scope,
    narrow_scope,
)
from app.config import get_settings
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

FIELDS_HIDDEN_NOTE = (
    "Field details are hidden: your access covers only some of this data, not "
    "the whole dataset. Ask an atlas admin if you need them."
)


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


@dataclass(slots=True)
class _CallTrace:
    """What one execute() call touched, for its audit row (C15, C16).

    `scope`: None when no query ran, else the concrete compiled alternatives.
    `masking`: None, or the applied label masking (class and mode, row counts;
    never label values).
    """

    scope: dict[str, Any] | None = None
    masking: dict[str, Any] | None = None


# Per execute() call; a ContextVar so concurrent calls never share a trace.
_TRACE: ContextVar[_CallTrace | None] = ContextVar("atlas_call_trace", default=None)


def _policy_failed(label: str) -> AtlasAccessDeniedError:
    """An honest denial for a policy that could not be evaluated."""
    return AtlasAccessDeniedError(
        label,
        POLICY_FAILED,
        message=(
            f"{label} couldn't be checked against your access right now. "
            "Try again shortly."
        ),
    )


def _columns(entity: EntityDef | None) -> dict[str, str]:
    """Declared scope dimension -> SQL column text (vetted plugin YAML)."""
    if entity is None:
        return {}
    return {name: dim.column for name, dim in entity.scope_dimensions.items()}


def _provenance_scope(scope: RowScope | None) -> dict[str, Any]:
    """Dimension names only, never values (D3.11)."""
    if scope is None:
        return {"restricted": False, "dimensions": []}
    return {
        "restricted": True,
        "dimensions": sorted({dim for alternative in scope for dim in alternative}),
    }


def _well_formed(mode: MaskMode | None) -> bool:
    """A mode object of the wrong shape suppresses (fail closed)."""
    if mode is None:
        return False
    try:
        name, size = mode.mode, mode.bucket_size
    except Exception:
        return False
    return (
        isinstance(name, str) and isinstance(size, int) and not isinstance(size, bool)
    )


def _settings_pseudonym_key() -> str:
    """The deployment's pseudonym key, read lazily at mask time (C13).

    A missing or empty setting reads as "", which masking turns into
    `suppress` (fail closed).
    """
    return get_settings().atlas_pseudonym_key.strip()


def _audit_scope(compiled: CompiledScope) -> dict[str, Any]:
    if not compiled.restricted:
        return {"restricted": False}
    return {
        "restricted": True,
        "alternatives": [
            {dim: sorted(values) for dim, values in sorted(alternative.items())}
            for alternative in compiled.alternatives
        ],
    }


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
        *,
        pseudonym_key: str | None = None,
    ) -> None:
        self.caller = caller
        self._policy = policy
        self.db = db
        self._registry = registry
        self._pseudonym_key = pseudonym_key  # None: read from settings at mask time

    @property
    def registry(self) -> AtlasRegistry:
        return self._registry if self._registry is not None else get_registry()

    def visible_metrics(self) -> dict[str, MetricDef]:
        """Metrics this caller may see (spec §6, enforcement point 1)."""
        return {
            mid: m
            for mid, m in self.registry.metrics.items()
            if self._visible(metric_resource(m), self.registry.entities.get(m.entity))
        }

    def visible_funnels(self) -> dict[str, FunnelDef]:
        return {
            fid: f
            for fid, f in self.registry.funnels.items()
            if self._visible(funnel_resource(f), self.registry.entities.get(f.entity))
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

        trace = _CallTrace()
        token = _TRACE.set(trace)
        try:
            result, outcome = await self._run(tool, handlers[tool], arguments)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            await self._audit(tool, arguments, outcome, elapsed_ms)
        finally:
            _TRACE.reset(token)
        return result

    async def _run(
        self,
        tool: str,
        handler: Callable[..., Awaitable[dict[str, Any]]],
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], _Outcome]:
        outcome = _Outcome()
        try:
            result = await handler(**arguments)
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
            logger.exception(
                "atlas.tool_failed",
                tool=tool,
                user_id=str(self.caller.user_id),
                session_id=str(self.caller.session_id),
            )
            # Raw errors can echo bound scope values, so the audit row and the
            # answer carry none (the class name carries no values). Driver
            # errors in the log are value-free via hide_parameters.
            error = f"Internal error executing {tool}"
            outcome = _Outcome(False, f"{error} ({type(exc).__name__})")
            result = {"error": error}
        return result, outcome

    async def _audit(
        self,
        tool: str,
        arguments: dict[str, Any],
        outcome: _Outcome,
        duration_ms: int,
    ) -> None:
        if self.db is None:
            return
        trace = _TRACE.get()
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
                scope=trace.scope if trace else None,
                masking=trace.masking if trace else None,
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

    def _row_scope(self, resource: str, entity: EntityDef | None) -> RowScope | None:
        """Rows this caller may read of an allowed resource (D3.3, D3.7).

        `None` = all rows. Raises `ScopeCompileError` when the scope grants
        nothing here (empty, undeclared dimension, over a limit): the resource
        is then denied, never run unscoped. A failing policy, or a scope of the
        wrong shape, raises `AtlasPolicyError`.
        """
        columns = _columns(entity)
        try:
            narrowed = narrow_scope(self._policy.row_scope(resource), columns)
            # Trial compile: bind limits and column text fail here, so discovery
            # agrees with execution.
            compile_scope(SCOPE_TOKEN, columns, narrowed)
        except ScopeCompileError:
            raise
        except Exception as exc:
            raise AtlasPolicyError(POLICY_FAILED) from exc
        return narrowed

    def _visible(self, resource: str, entity: EntityDef | None) -> bool:
        """Discovery check (point 1): allowed with a usable row scope.

        A failing policy, or a scope that grants nothing here, hides the item.
        """
        try:
            if not self._allowed(resource):
                return False
            self._row_scope(resource, entity)
        except AtlasPolicyError:
            logger.exception("atlas.policy_error", resource=resource)
            return False
        except ScopeCompileError as exc:
            # The reason is fixed text, never values. A dimension this data
            # lacks is routine (a csm scope over deepsales/*); others are
            # misconfiguration (empty scope, a cap, bad column text).
            reason = str(exc)
            log = logger.info if reason == UNDECLARED else logger.warning
            log("atlas.scope_hidden", resource=resource, reason=reason)
            return False
        return True

    def _denied(self, resource: str, label: str) -> AtlasAccessDeniedError:
        try:
            reason = self._policy.deny_reason(resource)
        except Exception:
            logger.exception("atlas.policy_error", resource=resource)
            reason = POLICY_FAILED
        return AtlasAccessDeniedError(label, reason)

    def _hidden(
        self, resource: str, label: str, entity: EntityDef | None
    ) -> AtlasAccessDeniedError:
        """The denial for a resource discovery hid, with its real reason.

        An allowed resource hidden by its row scope is denied with the scope
        reason, never the policy's (which would say "allowed by grant ...").
        """
        try:
            if self._allowed(resource):
                self._row_scope(resource, entity)
        except AtlasPolicyError:
            logger.exception("atlas.policy_error", resource=resource)
            # Discovery keeps phase 2's message: the entity is simply hidden.
            return AtlasAccessDeniedError(label, POLICY_FAILED)
        except ScopeCompileError as exc:
            return AtlasAccessDeniedError(label, str(exc))
        return self._denied(resource, label)

    def _authorize(
        self, resource: str, label: str, entity: EntityDef | None
    ) -> RowScope | None:
        """Execution check (point 2): returns the caller's row scope.

        A policy-evaluation failure is not a real denial — it gets its own
        honest message, never "isn't available to you" (that claims the
        policy was consulted and said no). A scope that grants nothing here
        is a denial whose audited reason is the compile error.
        """
        try:
            if not self._allowed(resource):
                raise self._denied(resource, label)
            return self._row_scope(resource, entity)
        except AtlasPolicyError as exc:
            logger.exception("atlas.policy_error", resource=resource)
            raise _policy_failed(label) from exc
        except ScopeCompileError as exc:
            raise AtlasAccessDeniedError(label, str(exc)) from exc

    def _entity_visible(self, entity: EntityDef) -> bool:
        return (
            self._visible(entity_resource(entity), entity)
            or any(self._visible(metric_resource(m), entity) for m in entity.metrics)
            or any(self._visible(funnel_resource(f), entity) for f in entity.funnels)
        )

    # ---- helpers ---------------------------------------------------------

    def _get_metric(
        self, metric_id: str
    ) -> tuple[MetricDef, EntityDef | None, RowScope | None]:
        metric = self.registry.metrics.get(metric_id)
        if metric is None:
            raise AtlasToolError(
                f"No metric '{metric_id}' in the atlas. Use list_metrics or "
                "search_atlas; if nothing fits, ask the user a clarifying question "
                "instead of guessing."
            )
        entity = self.registry.entities.get(metric.entity)
        scope = self._authorize(metric_resource(metric), metric.name, entity)
        return metric, entity, scope

    def _compile(
        self, sql: str, entity: EntityDef | None, scope: RowScope | None, label: str
    ) -> CompiledScope:
        """Compile `{{scope}}` into `sql` and record it for the audit row."""
        try:
            compiled = compile_scope(sql, _columns(entity), scope)
        except ScopeCompileError as exc:
            raise AtlasAccessDeniedError(label, str(exc)) from exc
        trace = _TRACE.get()
        if trace is not None:
            trace.scope = _audit_scope(compiled)
        return compiled

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

    async def _freshness(
        self, entity: EntityDef | None, scope: RowScope | None
    ) -> str | None:
        if not entity or not entity.freshness_query:
            return None
        try:
            compiled = self._compile(entity.freshness_query, entity, scope, entity.name)
            row = await get_connector(entity.source).fetch_one(
                compiled.sql, compiled.params
            )
            if row:
                value = next(iter(row.values()), None)
                return str(value) if value is not None else None
        except ConnectorError:
            return None
        except AtlasAccessDeniedError:
            # Never run it unscoped; log the entity only, no scope values.
            logger.warning("atlas.freshness_scope_failed", entity=entity.id)
            return None
        return None

    async def _metric_provenance(
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
                scope=_provenance_scope(scope),
                masking=masking,
            )
        ]

    def _mask_inputs(self, label_class: str) -> tuple[bool, MaskMode | None]:
        """(cleared, mode) for a label class. A failing policy suppresses."""
        clearance = CLEARANCE_FOR_CLASS.get(label_class)
        if clearance is None:  # category (never masked) or unknown (suppressed)
            return False, None
        try:
            if self._policy.has_clearance(clearance):
                return True, None
            mode = self._policy.mask_mode(label_class)
        except Exception:
            logger.exception("atlas.policy_error", label_class=label_class)
            return False, None
        if mode is not None and not _well_formed(mode):
            # The label class only: never the mode's (possibly sensitive) fields.
            logger.warning("atlas.mask_mode_malformed", label_class=label_class)
            return False, None
        return False, mode

    def _key(self) -> str:
        if self._pseudonym_key is not None:
            return self._pseudonym_key
        return _settings_pseudonym_key()

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
        metric, entity, scope = self._get_metric(metric_id)
        params = self._metric_params(metric, start_date, end_date)
        compiled = self._compile(metric.query, entity, scope, metric.name)
        row = await get_connector(metric.source).fetch_one(
            compiled.sql, params | compiled.params
        )
        value = row.get("value") if row else None
        result = {
            "metric_id": metric.id,
            "name": metric.name,
            "unit": metric.unit,
            "value": float(value) if value is not None else 0.0,
            "provenance": await self._metric_provenance(
                "query_metric", metric, entity, scope
            ),
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
        fetched = await get_connector(metric.source).fetch_all(
            compiled.sql, params | compiled.params
        )
        rows = [
            {
                "label": r.get("label"),
                "value": float(r["value"]) if r.get("value") is not None else 0.0,
            }
            for r in fetched
        ]
        result, masking = self._masked(rows, metric.breakdown_label_class)
        return {
            "metric_id": metric.id,
            "name": metric.name,
            "unit": metric.unit,
            **result,
            "provenance": await self._metric_provenance(
                "metric_breakdown", metric, entity, scope, masking
            ),
        }

    def _masked(
        self, rows: list[dict[str, Any]], label_class: str | None
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Mask breakdown labels once, before they leave the kernel (D3.8).

        Returns the result fields and the provenance masking. A metric without
        a label class is treated as an unknown class: suppressed.
        """
        label_class = label_class or ""
        cleared, mode = (
            (False, None) if label_class == CATEGORY else self._mask_inputs(label_class)
        )
        masked = mask_breakdown(
            rows,
            label_class,
            cleared=cleared,
            mode=mode,
            key=self._key() if mode is not None else "",
        )
        result: dict[str, Any] = {"rows": masked.rows}
        if masked.suppressed_rows is not None:
            result["suppressed_rows"] = masked.suppressed_rows
        if masked.others_covers is not None:
            result["others_covers"] = masked.others_covers
        if masked.applied is None:
            return result, None
        trace = _TRACE.get()
        if trace is not None:
            trace.masking = {
                "label_class": label_class,
                "mode": masked.applied,
                "rows_in": len(rows),
                "rows_out": len(masked.rows),
            }
        return result, {"label_class": label_class, "mode": masked.applied}

    async def describe_entity(self, entity_id: str) -> dict[str, Any]:
        entity = self.registry.entities.get(entity_id)
        if entity is None:
            raise AtlasToolError(
                f"No entity '{entity_id}' in the atlas. Use search_atlas."
            )
        if not self._entity_visible(entity):
            raise self._hidden(entity_resource(entity), entity.name, entity)
        metrics, funnels = self.visible_metrics(), self.visible_funnels()
        # Field names need an entity-wide allow; item grants see only items (D3.10).
        entity_wide = self._visible(entity_resource(entity), entity)
        result: dict[str, Any] = {
            "id": entity.id,
            "name": entity.name,
            "description": entity.description,
            "source": entity.source,
            "fields": dict(entity.fields) if entity_wide else {},
            "pii_fields": list(entity.pii_fields) if entity_wide else [],
            "fields_hidden": not entity_wide,
            "metrics": [m.id for m in entity.metrics if m.id in metrics],
            "funnels": [f.id for f in entity.funnels if f.id in funnels],
        }
        if not entity_wide:
            result["note"] = FIELDS_HIDDEN_NOTE
        return result

    async def funnel_analyze(
        self, funnel_id: str, start_date: str, end_date: str
    ) -> dict[str, Any]:
        funnel = self.registry.funnels.get(funnel_id)
        if funnel is None:
            raise AtlasToolError(
                f"No funnel '{funnel_id}' in the atlas. Use list_metrics."
            )
        entity = self.registry.entities.get(funnel.entity)
        scope = self._authorize(funnel_resource(funnel), funnel.name, entity)
        params = _range_params(start_date, end_date)
        compiled_steps = [
            (step, self._compile(step.query, entity, scope, funnel.name))
            for step in funnel.steps
        ]
        connector = get_connector(funnel.source)

        steps: list[dict[str, Any]] = []
        prev_count: float | None = None
        worst: dict[str, Any] = {"step": None, "drop_pct": 0.0}
        for step, compiled in compiled_steps:
            row = await connector.fetch_one(compiled.sql, params | compiled.params)
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
                    freshness=await self._freshness(entity, scope),
                    scope=_provenance_scope(scope),
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

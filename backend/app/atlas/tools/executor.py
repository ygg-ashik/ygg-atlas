"""`AtlasTools`: the seven atlas tools for one caller, dispatched and audited.

It composes the door (authorisation and row scopes), the label masker and the
tool families, and owns what every query shares: compiling the row scope into
the SQL and reading data freshness for provenance.
"""

import time
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.atlas.models import EntityDef, FunnelDef, MetricDef
from app.atlas.policy import AtlasCaller, ResourcePolicy
from app.atlas.registry import AtlasRegistry
from app.atlas.scope import CompiledScope, RowScope, ScopeCompileError, compile_scope
from app.atlas.tools.audit import (
    CALL_TRACE,
    DENY,
    UNKNOWN_TOOL,
    CallTrace,
    Outcome,
    ToolHandler,
    record_scope,
    run_tool,
    write_audit,
)
from app.atlas.tools.discovery import DiscoveryTools
from app.atlas.tools.door import AtlasDoor, connector, scope_columns
from app.atlas.tools.errors import AtlasAccessDeniedError
from app.atlas.tools.funnels import FunnelTools
from app.atlas.tools.labels import LabelMasker
from app.atlas.tools.metrics import DEFAULT_BREAKDOWN_LIMIT, MetricTools
from app.sources import ConnectorError

logger = structlog.get_logger()


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
        self.db = db
        self._door = AtlasDoor(policy, registry)
        self._discovery = DiscoveryTools(self._door)
        self._metrics = MetricTools(
            self._door,
            LabelMasker(policy, pseudonym_key),
            compile_sql=self._compile,
            freshness=self._freshness,
        )
        self._funnels = FunnelTools(
            self._door, compile_sql=self._compile, freshness=self._freshness
        )

    @property
    def registry(self) -> AtlasRegistry:
        return self._door.registry

    def visible_metrics(self) -> dict[str, MetricDef]:
        """Metrics this caller may see (discovery)."""
        return self._door.visible_metrics()

    def visible_funnels(self) -> dict[str, FunnelDef]:
        return self._door.visible_funnels()

    async def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch + audit. Returns a JSON-safe dict; errors become {'error': ...}."""
        handlers: dict[str, ToolHandler] = {
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
            await write_audit(
                self.db,
                self.caller,
                tool,
                arguments,
                Outcome(False, error, DENY, UNKNOWN_TOOL),
                0,
            )
            return {"error": error}

        trace = CallTrace()
        token = CALL_TRACE.set(trace)
        try:
            result, outcome = await run_tool(
                self.caller, tool, handlers[tool], arguments
            )
            elapsed_ms = int((time.monotonic() - started) * 1000)
            await write_audit(
                self.db, self.caller, tool, arguments, outcome, elapsed_ms
            )
        finally:
            CALL_TRACE.reset(token)
        return result

    async def list_metrics(self) -> dict[str, Any]:
        return await self._discovery.list_metrics()

    async def query_metric(
        self, metric_id: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        return await self._metrics.query_metric(metric_id, start_date, end_date)

    async def metric_breakdown(
        self,
        metric_id: str,
        limit: int = DEFAULT_BREAKDOWN_LIMIT,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        return await self._metrics.metric_breakdown(
            metric_id, limit, start_date, end_date
        )

    async def describe_entity(self, entity_id: str) -> dict[str, Any]:
        return await self._discovery.describe_entity(entity_id)

    async def funnel_analyze(
        self, funnel_id: str, start_date: str, end_date: str
    ) -> dict[str, Any]:
        return await self._funnels.funnel_analyze(funnel_id, start_date, end_date)

    async def compare_periods(
        self,
        metric_id: str,
        period_a_start: str,
        period_a_end: str,
        period_b_start: str,
        period_b_end: str,
    ) -> dict[str, Any]:
        return await self._metrics.compare_periods(
            metric_id, period_a_start, period_a_end, period_b_start, period_b_end
        )

    async def search_atlas(self, query: str) -> dict[str, Any]:
        return await self._discovery.search_atlas(query)

    def _compile(
        self, sql: str, entity: EntityDef | None, scope: RowScope | None, label: str
    ) -> CompiledScope:
        """Compile `{{scope}}` into `sql` and record it for the audit row."""
        try:
            compiled = compile_scope(sql, scope_columns(entity), scope)
        except ScopeCompileError as exc:
            raise AtlasAccessDeniedError(label, str(exc)) from exc
        record_scope(compiled)
        return compiled

    async def _freshness(
        self, entity: EntityDef | None, scope: RowScope | None
    ) -> str | None:
        if not entity or not entity.freshness_query:
            return None
        try:
            compiled = self._compile(entity.freshness_query, entity, scope, entity.name)
            row = await connector(entity.source).fetch_one(
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

"""The one door to data: per-resource authorisation, row scopes and connectors.

Every tool family asks `AtlasDoor` before it touches data. Discovery hides a
resource the caller may not use; execution denies it with an honest reason. A
policy that fails to evaluate, or a row scope that grants nothing here, fails
closed.
"""

from collections.abc import Awaitable, Callable

import structlog

import app.atlas.tools as tools_package
from app.atlas.models import EntityDef, FunnelDef, MetricDef
from app.atlas.policy import (
    ResourcePolicy,
    entity_resource,
    funnel_resource,
    metric_resource,
)
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
from app.atlas.tools.errors import (
    POLICY_FAILED,
    AtlasAccessDeniedError,
    AtlasPolicyError,
    policy_failed,
)
from app.sources.base import Connector

logger = structlog.get_logger()

# Compile `{{scope}}` into a query for one resource label (records the scope
# for the audit row), and read an entity's data freshness under a scope.
Compile = Callable[[str, EntityDef | None, RowScope | None, str], CompiledScope]
Freshness = Callable[[EntityDef | None, RowScope | None], Awaitable[str | None]]


def connector(source: str) -> Connector:
    """The source's connector, looked up on the package at call time.

    `app.atlas.tools.get_connector` is the single seam every tool family reads
    connectors through, so replacing it there replaces it for all of them.
    """
    return tools_package.get_connector(source)


def scope_columns(entity: EntityDef | None) -> dict[str, str]:
    """Declared scope dimension -> SQL column text (vetted plugin YAML)."""
    if entity is None:
        return {}
    return {name: dim.column for name, dim in entity.scope_dimensions.items()}


class AtlasDoor:
    """Authorises one caller's policy against governed resources."""

    def __init__(self, policy: ResourcePolicy, registry: AtlasRegistry | None) -> None:
        self._policy = policy
        self._registry = registry

    @property
    def registry(self) -> AtlasRegistry:
        return self._registry if self._registry is not None else get_registry()

    def visible_metrics(self) -> dict[str, MetricDef]:
        """Metrics this caller may see (discovery)."""
        return {
            mid: m
            for mid, m in self.registry.metrics.items()
            if self.visible(metric_resource(m), self.registry.entities.get(m.entity))
        }

    def visible_funnels(self) -> dict[str, FunnelDef]:
        return {
            fid: f
            for fid, f in self.registry.funnels.items()
            if self.visible(funnel_resource(f), self.registry.entities.get(f.entity))
        }

    def _allowed(self, resource: str) -> bool:
        """The one call into the policy; any failure becomes AtlasPolicyError."""
        try:
            return self._policy.allows(resource)
        except Exception as exc:
            raise AtlasPolicyError(POLICY_FAILED) from exc

    def _row_scope(self, resource: str, entity: EntityDef | None) -> RowScope | None:
        """Rows this caller may read of an allowed resource.

        `None` = all rows. Raises `ScopeCompileError` when the scope grants
        nothing here (empty, undeclared dimension, over a limit): the resource
        is then denied, never run unscoped. A failing policy, or a scope of the
        wrong shape, raises `AtlasPolicyError`.
        """
        columns = scope_columns(entity)
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

    def visible(self, resource: str, entity: EntityDef | None) -> bool:
        """Discovery check: allowed with a usable row scope.

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

    def entity_visible(self, entity: EntityDef) -> bool:
        return (
            self.visible(entity_resource(entity), entity)
            or any(self.visible(metric_resource(m), entity) for m in entity.metrics)
            or any(self.visible(funnel_resource(f), entity) for f in entity.funnels)
        )

    def _denied(self, resource: str, label: str) -> AtlasAccessDeniedError:
        try:
            reason = self._policy.deny_reason(resource)
        except Exception:
            logger.exception("atlas.policy_error", resource=resource)
            reason = POLICY_FAILED
        # A crashed policy check offers no "request access" path.
        denied = None if reason == POLICY_FAILED else resource
        return AtlasAccessDeniedError(label, reason, resource=denied)

    def hidden(
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
            # A hidden entity keeps the plain denial message.
            return AtlasAccessDeniedError(label, POLICY_FAILED)
        except ScopeCompileError as exc:
            return AtlasAccessDeniedError(label, str(exc))
        return self._denied(resource, label)

    def authorize(
        self, resource: str, label: str, entity: EntityDef | None
    ) -> RowScope | None:
        """Execution check: returns the caller's row scope.

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
            raise policy_failed(label) from exc
        except ScopeCompileError as exc:
            raise AtlasAccessDeniedError(label, str(exc)) from exc

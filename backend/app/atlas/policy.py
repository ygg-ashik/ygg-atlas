"""What the atlas needs from an access policy (spec §6, enforcement points 1-5).

The atlas never imports app.access (ARCHITECTURE.md): the edges pass the caller's
evaluated Policy, which satisfies `ResourcePolicy` structurally.
Resource paths are `source/entity/item`; an entity alone is `source/entity`.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.atlas.masking import MaskMode
from app.atlas.models import EntityDef, FunnelDef, MetricDef
from app.atlas.scope import RowScope


class ResourcePolicy(Protocol):
    def allows(self, resource: str) -> bool: ...

    def deny_reason(self, resource: str) -> str: ...

    def row_scope(self, resource: str) -> RowScope | None:
        """Rows of an allowed resource: `None` = all rows; `()` = none (deny)."""
        ...

    def has_clearance(self, clearance: str) -> bool: ...

    def mask_mode(self, label_class: str) -> MaskMode | None:
        """`None` = no valid setting; the atlas then suppresses (fail closed)."""
        ...


@dataclass(frozen=True, slots=True)
class AtlasCaller:
    """Who runs the tools, as recorded in the audit log."""

    user_id: UUID
    auth_method: str
    surface: str = "chat"  # 'chat' | 'mcp' | 'api'
    session_id: UUID | None = None


def metric_resource(metric: MetricDef) -> str:
    return f"{metric.source}/{metric.entity}/{metric.id}"


def funnel_resource(funnel: FunnelDef) -> str:
    return f"{funnel.source}/{funnel.entity}/{funnel.id}"


def entity_resource(entity: EntityDef) -> str:
    return f"{entity.source}/{entity.id}"

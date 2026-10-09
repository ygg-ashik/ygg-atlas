"""Catalog metadata for the grant picker, with an optional per-user preview.

Pure: no I/O, no data, no numbers. Paths come from the atlas resource builders,
so the picker and the evaluator agree byte-for-byte (P5-D18). Decisions come from
the target's evaluated Policy, the same evaluator enforcement uses.
"""

from typing import Literal

from app.access import Policy
from app.atlas import AtlasRegistry
from app.atlas.models import EntityDef
from app.atlas.policy import entity_resource, funnel_resource, metric_resource
from app.insights.schemas import (
    CatalogEntityOut,
    CatalogItemOut,
    CatalogResourcesOut,
    CatalogSourceOut,
    ResourceDecisionOut,
)


def build_catalog_resources(
    registry: AtlasRegistry, policy: Policy | None
) -> CatalogResourcesOut:
    """Every source, entity, metric and funnel; with `policy`, each one's decision."""
    by_source: dict[str, list[EntityDef]] = {}
    for entity in registry.entities.values():
        by_source.setdefault(entity.source, []).append(entity)
    return CatalogResourcesOut(
        sources=[
            CatalogSourceOut(
                id=plugin.id,
                name=plugin.name,
                entities=[_entity(e, policy) for e in by_source.get(plugin.id, [])],
            )
            for plugin in registry.plugins.values()
        ],
        as_user=policy.user_id if policy is not None else None,
    )


def _entity(entity: EntityDef, policy: Policy | None) -> CatalogEntityOut:
    metrics = [
        _item(metric_resource(m), m.id, m.name, "metric", policy)
        for m in entity.metrics
    ]
    funnels = [
        _item(funnel_resource(f), f.id, f.name, "funnel", policy)
        for f in entity.funnels
    ]
    path = entity_resource(entity)
    return CatalogEntityOut(
        path=path,
        name=entity.name,
        items=metrics + funnels,
        decision=_decision(path, policy),
    )


def _item(
    path: str,
    item_id: str,
    name: str,
    kind: Literal["metric", "funnel"],
    policy: Policy | None,
) -> CatalogItemOut:
    return CatalogItemOut(
        path=path, id=item_id, name=name, kind=kind, decision=_decision(path, policy)
    )


def _decision(path: str, policy: Policy | None) -> ResourceDecisionOut | None:
    if policy is None:
        return None
    verdict = policy.decide(path)
    return ResourceDecisionOut(
        allowed=verdict.allowed,
        reason=verdict.reason,
        origin=verdict.rule.origin if verdict.rule is not None else None,
    )

"""Discovery tools: list_metrics, search_atlas and describe_entity.

They show only what the caller's policy lets them use, and never query data.
"""

from collections.abc import Collection
from typing import Any

from app.atlas.policy import entity_resource
from app.atlas.tools.door import AtlasDoor
from app.atlas.tools.errors import AtlasToolError

SEARCH_LIMIT = 10

FIELDS_HIDDEN_NOTE = (
    "Field details are hidden: your access covers only some of this data, not "
    "the whole dataset. Ask an atlas admin if you need them."
)


class DiscoveryTools:
    """The catalogue as one caller may see it."""

    def __init__(self, door: AtlasDoor) -> None:
        self._door = door

    async def list_metrics(self) -> dict[str, Any]:
        sources: dict[str, dict[str, Any]] = {}
        for plugin in self._door.registry.plugins.values():
            sources[plugin.id] = {
                "id": plugin.id,
                "name": plugin.name,
                "description": plugin.description,
                "metrics": [],
                "funnels": [],
            }
        for m in self._door.visible_metrics().values():
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
        for f in self._door.visible_funnels().values():
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

    async def describe_entity(self, entity_id: str) -> dict[str, Any]:
        door = self._door
        entity = door.registry.entities.get(entity_id)
        if entity is None:
            raise AtlasToolError(
                f"No entity '{entity_id}' in the atlas. Use search_atlas."
            )
        if not door.entity_visible(entity):
            raise door.hidden(entity_resource(entity), entity.name, entity)
        metrics, funnels = door.visible_metrics(), door.visible_funnels()
        # Field names need an entity-wide allow; item grants see only items.
        entity_wide = door.visible(entity_resource(entity), entity)
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

    async def search_atlas(self, query: str) -> dict[str, Any]:
        door = self._door
        entities = {
            e.id for e in door.registry.entities.values() if door.entity_visible(e)
        }
        visible: dict[str, Collection[str]] = {
            "metric": door.visible_metrics().keys(),
            "funnel": door.visible_funnels().keys(),
            "entity": entities,
        }
        results = door.registry.search(
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

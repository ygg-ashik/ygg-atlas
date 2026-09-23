"""Loads and indexes the semantic registry from every enabled source plugin.

Load-time validation is the enterprise guardrail: globally unique ids, and every
SQL query may reference only tables its plugin has allowlisted. A definition
that fails validation prevents startup — bad metrics never reach the agent.
"""

import re
from functools import lru_cache

import yaml

from app.atlas.models import EntityDef, FunnelDef, MetricDef
from app.sources import SourcePlugin, get_plugins

_TABLE_REF = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_.]*)", re.IGNORECASE)


def _referenced_tables(query: str) -> set[str]:
    return {t.lower() for t in _TABLE_REF.findall(query)}


class AtlasRegistry:
    def __init__(self, plugins: dict[str, SourcePlugin] | None = None):
        self.plugins = plugins if plugins is not None else get_plugins()
        self.entities: dict[str, EntityDef] = {}
        self.metrics: dict[str, MetricDef] = {}
        self.funnels: dict[str, FunnelDef] = {}
        for plugin in self.plugins.values():
            self._load_plugin(plugin)

    def _load_plugin(self, plugin: SourcePlugin) -> None:
        if not plugin.definitions_dir.is_dir():
            return
        for path in sorted(plugin.definitions_dir.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text())
            entity = EntityDef(**raw)
            entity.source = plugin.id
            where = f"{plugin.id}:{path.name}"
            if entity.id in self.entities:
                raise ValueError(f"Duplicate entity id '{entity.id}' in {where}")
            self.entities[entity.id] = entity

            for metric in entity.metrics:
                metric.entity = entity.id
                metric.source = plugin.id
                if metric.id in self.metrics:
                    raise ValueError(f"Duplicate metric id '{metric.id}' in {where}")
                if metric.time_scope not in ("range", "snapshot"):
                    raise ValueError(f"Metric '{metric.id}' has invalid time_scope in {where}")
                self._lint_tables(plugin, metric.query, f"metric '{metric.id}'", where)
                if metric.breakdown_query:
                    self._lint_tables(
                        plugin, metric.breakdown_query, f"breakdown of '{metric.id}'", where
                    )
                    if ":limit" not in metric.breakdown_query:
                        raise ValueError(f"Breakdown of '{metric.id}' must use :limit in {where}")
                self.metrics[metric.id] = metric

            for funnel in entity.funnels:
                funnel.entity = entity.id
                funnel.source = plugin.id
                if funnel.id in self.funnels:
                    raise ValueError(f"Duplicate funnel id '{funnel.id}' in {where}")
                for step in funnel.steps:
                    self._lint_tables(
                        plugin, step.query, f"funnel '{funnel.id}' step '{step.id}'", where
                    )
                self.funnels[funnel.id] = funnel

            if entity.freshness_query:
                self._lint_tables(plugin, entity.freshness_query, "freshness query", where)

    @staticmethod
    def _lint_tables(plugin: SourcePlugin, query: str, what: str, where: str) -> None:
        if plugin.allowed_tables is None:  # non-SQL source
            return
        illegal = _referenced_tables(query) - {t.lower() for t in plugin.allowed_tables}
        if illegal:
            raise ValueError(
                f"{what} in {where} references non-allowlisted tables: {sorted(illegal)}"
            )

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Keyword search over entities, metrics, and funnels."""
        terms = [t for t in query.lower().split() if t]
        results: list[tuple[int, dict]] = []

        def score(texts: str) -> int:
            texts = texts.lower()
            return sum(1 for t in terms if t in texts)

        for m in self.metrics.values():
            s = score(f"{m.id} {m.name} {m.description}")
            if s:
                results.append(
                    (
                        s,
                        {
                            "kind": "metric",
                            "id": m.id,
                            "name": m.name,
                            "description": m.description,
                            "entity": m.entity,
                            "source": m.source,
                        },
                    )
                )
        for f in self.funnels.values():
            s = score(f"{f.id} {f.name} {f.description}")
            if s:
                results.append(
                    (
                        s,
                        {
                            "kind": "funnel",
                            "id": f.id,
                            "name": f.name,
                            "description": f.description,
                            "entity": f.entity,
                            "source": f.source,
                        },
                    )
                )
        for e in self.entities.values():
            s = score(f"{e.id} {e.name} {e.description}")
            if s:
                results.append(
                    (
                        s,
                        {
                            "kind": "entity",
                            "id": e.id,
                            "name": e.name,
                            "description": e.description,
                            "source": e.source,
                        },
                    )
                )

        results.sort(key=lambda r: -r[0])
        return [r for _, r in results[:limit]]


@lru_cache
def get_registry() -> AtlasRegistry:
    return AtlasRegistry()


def reset_registry() -> None:
    """Test helper: clear the cached registry (pair with sources.reset_plugins)."""
    get_registry.cache_clear()

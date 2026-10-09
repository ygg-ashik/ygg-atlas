"""Loads and indexes the semantic registry from every enabled source plugin.

Load-time validation is the enterprise guardrail: globally unique ids, ids that are
safe resource-path segments (`^[a-z0-9_]+$`, and no metric and funnel sharing an
id within one entity, since both map to `source/entity/id`), and every SQL query
may reference only tables its plugin has allowlisted. Row scope fails closed at
load: in an entity that declares `scope_dimensions`, every query carries the
`{{scope}}` placeholder, no other `{{...}}` template exists anywhere, dimension
names, columns and `self` attributes are linted, one dimension name maps to one
`self` attribute registry-wide, and every breakdown declares its label class.
A definition that fails validation prevents startup — bad metrics never reach
the agent.
"""

import re
from collections.abc import Callable, Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.atlas.masking import CATEGORY, CLEARANCE_FOR_CLASS
from app.atlas.models import EntityDef, FunnelDef, MetricDef, ScopeDimensionDef
from app.atlas.scope import (
    COLUMN_PATTERN,
    RESERVED_BIND_PREFIX,
    SCOPE_TOKEN,
    uses_reserved_bind,
)
from app.sources import SourcePlugin, get_plugins

_ID = re.compile(r"^[a-z0-9_]+$")
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_.]*)", re.IGNORECASE)

# Every label class a breakdown may declare: 'category' plus each maskable class.
LABEL_CLASSES: tuple[str, ...] = (CATEGORY, *sorted(CLEARANCE_FOR_CLASS))
RESERVED_DIMENSIONS = frozenset({"tenant"})
_DIMENSION = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ATTRIBUTE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PLACEHOLDER = re.compile(r"\{\{.*?\}\}", re.DOTALL)

# One catalog row: source id, entity id, dimension name, self attribute, description.
type ScopeCatalogEntry = tuple[str, str, str, str | None, str]


def _referenced_tables(query: str) -> set[str]:
    return {t.lower() for t in _TABLE_REF.findall(query)}


def _lint_id(kind: str, value: str, where: str) -> None:
    """Ids are resource-path segments that grants match (`source/entity/id`)."""
    if not _ID.fullmatch(value):
        raise ValueError(
            f"{kind} id '{value}' in {where} must match {_ID.pattern} "
            "(lowercase letters, digits and underscores)"
        )


class AtlasRegistry:
    def __init__(self, plugins: dict[str, SourcePlugin] | None = None) -> None:
        self.plugins = plugins if plugins is not None else get_plugins()
        self.entities: dict[str, EntityDef] = {}
        self.metrics: dict[str, MetricDef] = {}
        self.funnels: dict[str, FunnelDef] = {}
        for plugin in self.plugins.values():
            self._load_plugin(plugin)
        self._lint_self_attributes()

    def _load_plugin(self, plugin: SourcePlugin) -> None:
        if not plugin.definitions_dir.is_dir():
            return
        for path in sorted(plugin.definitions_dir.glob("*.yaml")):
            self._load_definition_file(plugin, path)

    def _load_definition_file(self, plugin: SourcePlugin, path: Path) -> None:
        raw = yaml.safe_load(path.read_text())
        entity = EntityDef(**raw)
        entity.source = plugin.id
        where = f"{plugin.id}:{path.name}"
        _lint_id("entity", entity.id, where)
        if entity.id in self.entities:
            raise ValueError(f"Duplicate entity id '{entity.id}' in {where}")
        self.entities[entity.id] = entity

        for metric in entity.metrics:
            self._register_metric(plugin, entity, metric, where)

        for funnel in entity.funnels:
            self._register_funnel(plugin, entity, funnel, where)

        shared = {m.id for m in entity.metrics} & {f.id for f in entity.funnels}
        if shared:
            raise ValueError(
                f"Metric and funnel ids {sorted(shared)} in {where} share "
                f"the same resource path under entity '{entity.id}'"
            )

        if entity.freshness_query:
            self._lint_tables(plugin, entity.freshness_query, "freshness query", where)

        _lint_scope(plugin, entity, where)

    def _register_metric(
        self, plugin: SourcePlugin, entity: EntityDef, metric: MetricDef, where: str
    ) -> None:
        metric.entity = entity.id
        metric.source = plugin.id
        _lint_id("metric", metric.id, where)
        if metric.id in self.metrics:
            raise ValueError(f"Duplicate metric id '{metric.id}' in {where}")
        if metric.time_scope not in ("range", "snapshot"):
            raise ValueError(f"Metric '{metric.id}' has invalid time_scope in {where}")
        self._lint_tables(plugin, metric.query, f"metric '{metric.id}'", where)
        if metric.breakdown_query:
            self._lint_tables(
                plugin,
                metric.breakdown_query,
                f"breakdown of '{metric.id}'",
                where,
            )
            if ":limit" not in metric.breakdown_query:
                raise ValueError(
                    f"Breakdown of '{metric.id}' must use :limit in {where}"
                )
            if metric.breakdown_label_class is None:
                raise ValueError(
                    f"Metric '{metric.id}' must declare breakdown_label_class "
                    f"(one of {', '.join(LABEL_CLASSES)}) in {where}"
                )
        if (
            metric.breakdown_label_class is not None
            and metric.breakdown_label_class not in LABEL_CLASSES
        ):
            raise ValueError(
                f"Metric '{metric.id}' has unknown breakdown_label_class "
                f"'{metric.breakdown_label_class}' in {where} "
                f"(one of {', '.join(LABEL_CLASSES)})"
            )
        self.metrics[metric.id] = metric

    def _register_funnel(
        self, plugin: SourcePlugin, entity: EntityDef, funnel: FunnelDef, where: str
    ) -> None:
        funnel.entity = entity.id
        funnel.source = plugin.id
        _lint_id("funnel", funnel.id, where)
        if funnel.id in self.funnels:
            raise ValueError(f"Duplicate funnel id '{funnel.id}' in {where}")
        for step in funnel.steps:
            self._lint_tables(
                plugin,
                step.query,
                f"funnel '{funnel.id}' step '{step.id}'",
                where,
            )
        self.funnels[funnel.id] = funnel

    @staticmethod
    def _lint_tables(plugin: SourcePlugin, query: str, what: str, where: str) -> None:
        if plugin.allowed_tables is None:  # non-SQL source
            return
        illegal = _referenced_tables(query) - {t.lower() for t in plugin.allowed_tables}
        if illegal:
            raise ValueError(
                f"{what} in {where} references non-allowlisted tables: "
                f"{sorted(illegal)}"
            )

    def _lint_self_attributes(self) -> None:
        """A dimension name means one thing registry-wide, so `$self` on a grant
        spanning several entities resolves to one attribute (or none)."""
        seen: dict[str, tuple[str | None, str]] = {}
        for entity in self.entities.values():
            for name, dimension in entity.scope_dimensions.items():
                where = f"{entity.source}/{entity.id}"
                if name not in seen:
                    seen[name] = (dimension.self_attribute, where)
                    continue
                first, first_where = seen[name]
                if first != dimension.self_attribute:
                    raise ValueError(
                        f"Scope dimension '{name}' must have one self attribute "
                        f"across the registry: {first_where} declares {first!r}, "
                        f"{where} declares {dimension.self_attribute!r}"
                    )

    def scope_catalog(self) -> list[ScopeCatalogEntry]:
        """Every declared scope dimension, sorted, for the access mirror."""
        return sorted(
            (
                entity.source,
                entity.id,
                name,
                dimension.self_attribute,
                dimension.description,
            )
            for entity in self.entities.values()
            for name, dimension in entity.scope_dimensions.items()
        )

    def search(
        self,
        query: str,
        limit: int = 10,
        visible: Callable[[str, str], bool] | None = None,
    ) -> list[dict[str, Any]]:
        """Keyword search over entities, metrics, and funnels.

        `visible(kind, id)` drops what the caller may not see before ranking
        and truncation, so hidden matches never crowd out visible ones.
        """
        terms = [t for t in query.lower().split() if t]
        results: list[tuple[int, dict[str, Any]]] = []

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

        if visible is not None:
            results = [r for r in results if visible(r[1]["kind"], r[1]["id"])]
        results.sort(key=lambda r: -r[0])
        return [r for _, r in results[:limit]]


def _queries(entity: EntityDef) -> Iterator[tuple[str, str]]:
    """Every SQL query of an entity, as `(what, sql)`."""
    for metric in entity.metrics:
        yield f"metric '{metric.id}'", metric.query
        if metric.breakdown_query:
            yield f"breakdown of '{metric.id}'", metric.breakdown_query
    for funnel in entity.funnels:
        for step in funnel.steps:
            yield f"funnel '{funnel.id}' step '{step.id}'", step.query
    if entity.freshness_query:
        yield "freshness query", entity.freshness_query


def _lint_dimension(name: str, dimension: ScopeDimensionDef, where: str) -> None:
    if not _DIMENSION.fullmatch(name):
        raise ValueError(
            f"scope dimension '{name}' in {where} must match {_DIMENSION.pattern}"
        )
    if name in RESERVED_DIMENSIONS:
        raise ValueError(f"scope dimension '{name}' is reserved ({where})")
    if not COLUMN_PATTERN.fullmatch(dimension.column):
        raise ValueError(
            f"scope dimension '{name}' column '{dimension.column}' in {where} "
            f"must match {COLUMN_PATTERN.pattern}"
        )
    if dimension.self_attribute is not None and not _ATTRIBUTE.fullmatch(
        dimension.self_attribute
    ):
        raise ValueError(
            f"scope dimension '{name}' self attribute '{dimension.self_attribute}' "
            f"in {where} must match {_ATTRIBUTE.pattern}"
        )


def _lint_scope(plugin: SourcePlugin, entity: EntityDef, where: str) -> None:
    """Fail closed: a scoped entity has no unscoped query; no other template exists."""
    scoped = bool(entity.scope_dimensions)
    if scoped and plugin.allowed_tables is None:
        raise ValueError(
            f"Entity '{entity.id}' in {where} declares scope_dimensions, "
            "but its plugin is a non-SQL source"
        )
    for name, dimension in entity.scope_dimensions.items():
        _lint_dimension(name, dimension, where)
    for what, sql in _queries(entity):
        rest = sql.replace(SCOPE_TOKEN, "")
        if "{{" in rest or "}}" in rest:
            found = _PLACEHOLDER.findall(rest) or ["{{" if "{{" in rest else "}}"]
            raise ValueError(
                f"{what} in {where} has an unknown template placeholder "
                f"{found[0]!r} (only {SCOPE_TOKEN} is allowed)"
            )
        if uses_reserved_bind(sql):
            raise ValueError(
                f"{what} in {where} uses the reserved bind prefix "
                f"{RESERVED_BIND_PREFIX} (kept for compiled row scopes)"
            )
        has_token = SCOPE_TOKEN in sql
        if scoped and not has_token:
            raise ValueError(
                f"{what} in {where} must contain {SCOPE_TOKEN}: entity "
                f"'{entity.id}' declares scope_dimensions"
            )
        if not scoped and has_token:
            raise ValueError(
                f"{what} in {where} uses {SCOPE_TOKEN} but entity '{entity.id}' "
                "declares no scope_dimensions"
            )


@lru_cache
def get_registry() -> AtlasRegistry:
    return AtlasRegistry()


def reset_registry() -> None:
    """Test helper: clear the cached registry (pair with sources.reset_plugins)."""
    get_registry.cache_clear()

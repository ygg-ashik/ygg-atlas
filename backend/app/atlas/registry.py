"""Loads and indexes the semantic registry from YAML definition files."""

from functools import lru_cache
from pathlib import Path

import yaml

from app.atlas.models import EntityDef, FunnelDef, MetricDef

DEFINITIONS_DIR = Path(__file__).parent / "definitions"


class AtlasRegistry:
    def __init__(self, definitions_dir: Path = DEFINITIONS_DIR):
        self.entities: dict[str, EntityDef] = {}
        self.metrics: dict[str, MetricDef] = {}
        self.funnels: dict[str, FunnelDef] = {}
        self._load(definitions_dir)

    def _load(self, definitions_dir: Path) -> None:
        for path in sorted(definitions_dir.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text())
            entity = EntityDef(**raw)
            if entity.id in self.entities:
                raise ValueError(f"Duplicate entity id '{entity.id}' in {path.name}")
            self.entities[entity.id] = entity
            for metric in entity.metrics:
                metric.entity = entity.id
                metric.source = metric.source or entity.source
                if metric.id in self.metrics:
                    raise ValueError(f"Duplicate metric id '{metric.id}' in {path.name}")
                self.metrics[metric.id] = metric
            for funnel in entity.funnels:
                funnel.entity = entity.id
                funnel.source = funnel.source or entity.source
                if funnel.id in self.funnels:
                    raise ValueError(f"Duplicate funnel id '{funnel.id}' in {path.name}")
                self.funnels[funnel.id] = funnel

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Keyword search over entities, metrics, and funnels."""
        terms = [t for t in query.lower().split() if t]
        results: list[tuple[int, dict]] = []

        def score(text: str) -> int:
            text = text.lower()
            return sum(1 for t in terms if t in text)

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
                        },
                    )
                )

        results.sort(key=lambda r: -r[0])
        return [r for _, r in results[:limit]]


@lru_cache
def get_registry() -> AtlasRegistry:
    return AtlasRegistry()

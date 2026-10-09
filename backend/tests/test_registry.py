import importlib
import pkgutil
from pathlib import Path

import pytest

from app.atlas.registry import AtlasRegistry
from app.sources import get_plugins
from app.sources.base import Connector, SourcePlugin


def _no_connector() -> Connector:
    raise AssertionError("registry tests never query a connector")


def _plugin(
    tmp_path: Path, yaml_text: str, allowed: set[str] | None = None
) -> SourcePlugin:
    (tmp_path / "defs").mkdir(exist_ok=True)
    (tmp_path / "defs" / "test.yaml").write_text(yaml_text)
    return SourcePlugin(
        id="testsrc",
        name="Test source",
        description="",
        definitions_dir=tmp_path / "defs",
        connector_factory=_no_connector,
        allowed_tables=allowed,
    )


def test_registry_loads_all_enabled_plugins(db):
    registry = AtlasRegistry()
    assert "revenue" in registry.metrics
    assert "customers_total" in registry.metrics
    assert "checkout_funnel" in registry.funnels
    assert registry.metrics["revenue"].source == "demo"
    assert registry.metrics["revenue"].breakdown_query is not None
    assert registry.metrics["customers_total"].time_scope == "snapshot"


def test_search_includes_source(db):
    registry = AtlasRegistry()
    results = registry.search("revenue")
    assert any(r["id"] == "revenue" and r["source"] == "demo" for r in results)


def test_search_applies_the_visibility_predicate_before_the_limit(db):
    registry = AtlasRegistry()
    everything = registry.search("revenue customers orders", limit=50)
    hidden = {r["id"] for r in everything[:3]}

    results = registry.search(
        "revenue customers orders",
        limit=3,
        visible=lambda kind, id_: id_ not in hidden,
    )

    assert len(results) == min(3, len(everything) - len(hidden))
    assert not hidden & {r["id"] for r in results}


def test_search_no_match_returns_empty(db):
    assert AtlasRegistry().search("xyzzy nonexistent") == []


def test_table_lint_rejects_non_allowlisted_tables(tmp_path):
    plugin = _plugin(
        tmp_path,
        """
id: sneaky
name: Sneaky
metrics:
  - id: sneaky_metric
    name: Sneaky metric
    query: >
      SELECT COUNT(*) AS value FROM secret_table
      WHERE created_at >= :start AND created_at <= :end
""",
        allowed={"demo_orders"},
    )
    with pytest.raises(ValueError, match=r"non-allowlisted tables.*secret_table"):
        AtlasRegistry(plugins={"testsrc": plugin})


def test_invalid_time_scope_rejected(tmp_path):
    plugin = _plugin(
        tmp_path,
        """
id: bad
name: Bad
metrics:
  - id: bad_metric
    name: Bad metric
    time_scope: hourly
    query: SELECT 1 AS value
""",
    )
    with pytest.raises(ValueError, match="invalid time_scope"):
        AtlasRegistry(plugins={"testsrc": plugin})


def test_breakdown_without_limit_rejected(tmp_path):
    plugin = _plugin(
        tmp_path,
        """
id: bad
name: Bad
metrics:
  - id: bad_metric
    name: Bad metric
    time_scope: snapshot
    query: SELECT 1 AS value
    breakdown_query: SELECT 'a' AS label, 1 AS value
""",
    )
    with pytest.raises(ValueError, match="must use :limit"):
        AtlasRegistry(plugins={"testsrc": plugin})


def test_duplicate_metric_id_across_plugins_rejected(tmp_path, db):
    plugin = _plugin(
        tmp_path,
        """
id: clash_entity
name: Clash
metrics:
  - id: revenue
    name: Clashing revenue
    time_scope: snapshot
    query: SELECT 1 AS value
""",
    )
    plugins = dict(get_plugins()) | {"testsrc": plugin}
    with pytest.raises(ValueError, match="Duplicate metric id 'revenue'"):
        AtlasRegistry(plugins=plugins)


# ---- ids are resource-path segments -------------------------------------------

_FUNNEL = """
funnels:
  - id: {funnel_id}
    name: A funnel
    steps:
      - id: first
        name: First
        query: SELECT 1 AS value
"""


@pytest.mark.parametrize(
    ("entity_id", "metric_id", "funnel_id", "what"),
    [
        ("Bad-Entity", "ok_metric", "ok_funnel", "entity id 'Bad-Entity'"),
        ("ok", "orders/total", "ok_funnel", "metric id 'orders/total'"),
        ("ok", "ok_metric", "Signup Funnel", "funnel id 'Signup Funnel'"),
        ("ok", "*", "ok_funnel", "metric id '\\*'"),
    ],
)
def test_ids_must_be_lowercase_path_safe(
    tmp_path, entity_id: str, metric_id: str, funnel_id: str, what: str
) -> None:
    plugin = _plugin(
        tmp_path,
        f"""
id: "{entity_id}"
name: Entity
metrics:
  - id: "{metric_id}"
    name: A metric
    time_scope: snapshot
    query: SELECT 1 AS value
"""
        + _FUNNEL.format(funnel_id=f'"{funnel_id}"'),
    )
    with pytest.raises(ValueError, match=f"{what}.*must match"):
        AtlasRegistry(plugins={"testsrc": plugin})


def test_a_metric_and_a_funnel_cannot_share_an_id_in_one_entity(tmp_path) -> None:
    plugin = _plugin(
        tmp_path,
        """
id: shop
name: Shop
metrics:
  - id: checkout
    name: Checkout
    time_scope: snapshot
    query: SELECT 1 AS value
"""
        + _FUNNEL.format(funnel_id="checkout"),
    )
    with pytest.raises(ValueError, match=r"'checkout'.*same resource path"):
        AtlasRegistry(plugins={"testsrc": plugin})


def test_every_shipped_definition_passes_the_lint() -> None:
    """Every plugin's definitions, configured here or not."""
    import app.sources as sources_pkg  # noqa: PLC0415

    plugins: dict[str, SourcePlugin] = {}
    for info in pkgutil.iter_modules(sources_pkg.__path__):
        if info.ispkg:
            manifest = importlib.import_module(f"app.sources.{info.name}.manifest")
            plugins[manifest.SOURCE.id] = manifest.SOURCE

    registry = AtlasRegistry(plugins=plugins)

    assert {"demo", "deepsales"} <= set(plugins)
    assert registry.metrics

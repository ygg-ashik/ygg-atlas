from pathlib import Path

import pytest

from app.atlas.registry import AtlasRegistry
from app.sources.base import SourcePlugin


def _plugin(tmp_path: Path, yaml_text: str, allowed: set[str] | None = None) -> SourcePlugin:
    (tmp_path / "defs").mkdir(exist_ok=True)
    (tmp_path / "defs" / "test.yaml").write_text(yaml_text)
    return SourcePlugin(
        id="testsrc",
        name="Test source",
        description="",
        definitions_dir=tmp_path / "defs",
        connector_factory=lambda: None,
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
    with pytest.raises(ValueError, match="non-allowlisted tables.*secret_table"):
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
    from app.sources import get_plugins

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

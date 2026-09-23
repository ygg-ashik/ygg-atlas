from app.atlas.registry import AtlasRegistry


def test_registry_loads_definitions():
    registry = AtlasRegistry()
    assert "revenue" in registry.metrics
    assert "orders_count" in registry.metrics
    assert "new_customers" in registry.metrics
    assert "checkout_funnel" in registry.funnels
    assert {"order", "customer"} <= set(registry.entities)


def test_metric_inherits_entity_source():
    registry = AtlasRegistry()
    metric = registry.metrics["revenue"]
    assert metric.source == "appdb"
    assert metric.entity == "order"


def test_search_finds_metrics_by_keyword():
    registry = AtlasRegistry()
    results = registry.search("revenue")
    ids = [r["id"] for r in results]
    assert "revenue" in ids
    assert "b2b_revenue" in ids


def test_search_finds_funnel():
    registry = AtlasRegistry()
    results = registry.search("checkout drop")
    assert any(r["kind"] == "funnel" for r in results)


def test_search_no_match_returns_empty():
    registry = AtlasRegistry()
    assert registry.search("xyzzy nonexistent") == []

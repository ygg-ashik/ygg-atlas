import importlib
import pkgutil
from pathlib import Path

import pytest

from app.atlas.registry import LABEL_CLASSES, AtlasRegistry
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


# ---- row scope and label classes (phase 3) -------------------------------------

_SCOPED_QUERIES = {
    "metric": "SELECT COUNT(*) AS value FROM t WHERE TRUE{metric}",
    "breakdown": (
        "SELECT channel AS label, COUNT(*) AS value FROM t WHERE TRUE{breakdown} "
        "GROUP BY channel LIMIT :limit"
    ),
    "funnel step": "SELECT COUNT(DISTINCT id) AS value FROM t WHERE TRUE{step}",
    "freshness query": "SELECT MAX(created_at) FROM t WHERE TRUE{freshness}",
}


def _scoped_entity(
    *,
    dimensions: str = "  channel:\n    column: channel\n",
    omit: str | None = None,
    entity_id: str = "shop",
    metric_id: str = "shop_orders",
    label_class: str | None = "category",
) -> str:
    def token(what: str) -> str:
        return "" if what == omit else " {{scope}}"

    label = f"    breakdown_label_class: {label_class}\n" if label_class else ""
    dims = f"scope_dimensions:\n{dimensions}" if dimensions else ""
    breakdown = _SCOPED_QUERIES["breakdown"].format(breakdown=token("breakdown"))
    return (
        f"id: {entity_id}\nname: Shop\n{dims}"
        "freshness_query: "
        + repr(
            _SCOPED_QUERIES["freshness query"].format(
                freshness=token("freshness query")
            )
        )
        + f"""
metrics:
  - id: {metric_id}
    name: Orders
    time_scope: snapshot
    query: {_SCOPED_QUERIES["metric"].format(metric=token("metric"))!r}
    breakdown_query: {breakdown!r}
{label}funnels:
  - id: {metric_id}_funnel
    name: Funnel
    steps:
      - id: first
        name: First
        query: {_SCOPED_QUERIES["funnel step"].format(step=token("funnel step"))!r}
"""
    )


def _load(
    tmp_path: Path, yaml_text: str, allowed: set[str] | None = None
) -> AtlasRegistry:
    plugin = _plugin(tmp_path, yaml_text, allowed={"t"} if allowed is None else allowed)
    return AtlasRegistry(plugins={"testsrc": plugin})


def test_a_fully_scoped_entity_loads(tmp_path) -> None:
    registry = _load(tmp_path, _scoped_entity())

    dimension = registry.entities["shop"].scope_dimensions["channel"]
    assert dimension.column == "channel"
    assert dimension.self_attribute is None
    assert registry.metrics["shop_orders"].breakdown_label_class == "category"


@pytest.mark.parametrize(
    ("omit", "named"),
    [
        ("metric", "metric 'shop_orders'"),
        ("breakdown", "breakdown of 'shop_orders'"),
        ("funnel step", "funnel 'shop_orders_funnel' step 'first'"),
        ("freshness query", "freshness query"),
    ],
)
def test_scoped_entity_queries_must_contain_scope(
    tmp_path, omit: str, named: str
) -> None:
    with pytest.raises(
        ValueError, match=rf"{named} in testsrc:test\.yaml must contain"
    ):
        _load(tmp_path, _scoped_entity(omit=omit))


@pytest.mark.parametrize(
    "placeholder", ["{{tenant}}", "{{ scope }}", "{{scope", "scope}}"]
)
@pytest.mark.parametrize("scoped", [True, False])
def test_unknown_template_placeholders_are_rejected(
    tmp_path, placeholder: str, scoped: bool
) -> None:
    yaml_text = (
        _scoped_entity()
        if scoped
        else _scoped_entity(dimensions="", omit=None).replace(" {{scope}}", "")
    )
    yaml_text = yaml_text.replace(
        "COUNT(*) AS value FROM t WHERE TRUE",
        f"COUNT(*) AS value FROM t WHERE TRUE {placeholder}",
        1,
    )
    with pytest.raises(ValueError, match="template placeholder"):
        _load(tmp_path, yaml_text)


def test_scope_placeholder_without_dimensions_is_rejected(tmp_path) -> None:
    with pytest.raises(
        ValueError, match=r"uses \{\{scope\}\} but entity 'shop' declares no"
    ):
        _load(tmp_path, _scoped_entity(dimensions=""))


def test_scope_dimensions_on_a_non_sql_plugin_are_rejected(tmp_path) -> None:
    plugin = _plugin(tmp_path, _scoped_entity(), allowed=None)
    with pytest.raises(ValueError, match="non-SQL"):
        AtlasRegistry(plugins={"testsrc": plugin})


def test_tenant_is_a_reserved_dimension(tmp_path) -> None:
    with pytest.raises(ValueError, match="'tenant' is reserved"):
        _load(tmp_path, _scoped_entity(dimensions="  tenant:\n    column: tenant_id\n"))


@pytest.mark.parametrize(
    ("dimension", "column", "ok"),
    [
        ("Bad", "channel", False),
        ("a-b", "channel", False),
        ("1st", "channel", False),
        ("channel", "x; drop", False),
        ("channel", "a.b.c", False),
        ("channel", "1col", False),
        ("a" * 65, "channel", False),
        ("a" * 64, "channel", True),
        ("csm", "c.csm_name", True),
        ("csm", "assignee_name", True),
    ],
)
def test_dimension_names_and_columns_are_linted(
    tmp_path, dimension: str, column: str, ok: bool
) -> None:
    yaml_text = _scoped_entity(dimensions=f"  {dimension}:\n    column: '{column}'\n")
    if ok:
        assert _load(tmp_path, yaml_text).entities["shop"].scope_dimensions[dimension]
    else:
        with pytest.raises(ValueError, match="scope dimension"):
            _load(tmp_path, yaml_text)


@pytest.mark.parametrize(
    ("attribute", "ok"),
    [
        ("csm_name", True),
        ("rep_name", True),
        ("CsmName", False),
        ("1csm", False),
        ("csm-name", False),
        ("a" * 65, False),
        ("", False),
    ],
)
def test_self_attribute_is_linted(tmp_path, attribute: str, ok: bool) -> None:
    yaml_text = _scoped_entity(
        dimensions=f"  csm:\n    column: csm_name\n    self: '{attribute}'\n"
    )
    if ok:
        registry = _load(tmp_path, yaml_text)
        assert (
            registry.entities["shop"].scope_dimensions["csm"].self_attribute
            == attribute
        )
    else:
        with pytest.raises(ValueError, match="self attribute"):
            _load(tmp_path, yaml_text)


def test_unknown_keys_on_a_scope_dimension_are_rejected(tmp_path) -> None:
    yaml_text = _scoped_entity(
        dimensions="  csm:\n    column: csm_name\n    slef: csm_name\n"
    )
    with pytest.raises(ValueError, match="slef"):
        _load(tmp_path, yaml_text)


def _two_entities(
    tmp_path: Path, first_self: str | None, second_self: str | None
) -> AtlasRegistry:
    defs = tmp_path / "defs"
    defs.mkdir(exist_ok=True)
    for name, entity_id, self_attr in (
        ("a.yaml", "shop_a", first_self),
        ("b.yaml", "shop_b", second_self),
    ):
        self_line = f"    self: {self_attr}\n" if self_attr else ""
        (defs / name).write_text(
            _scoped_entity(
                dimensions=f"  csm:\n    column: csm_name\n{self_line}",
                entity_id=entity_id,
                metric_id=f"{entity_id}_orders",
            )
        )
    plugin = SourcePlugin(
        id="testsrc",
        name="Test source",
        description="",
        definitions_dir=defs,
        connector_factory=_no_connector,
        allowed_tables={"t"},
    )
    return AtlasRegistry(plugins={"testsrc": plugin})


@pytest.mark.parametrize(
    ("first", "second"), [("csm_name", "csm_email"), ("csm_name", None)]
)
def test_a_dimension_has_one_self_attribute_across_the_registry(
    tmp_path, first: str, second: str | None
) -> None:
    with pytest.raises(ValueError, match=r"dimension 'csm'.*one self attribute"):
        _two_entities(tmp_path, first, second)


@pytest.mark.parametrize("self_attr", ["csm_name", None])
def test_entities_may_share_a_dimension_with_the_same_self_attribute(
    tmp_path, self_attr: str | None
) -> None:
    registry = _two_entities(tmp_path, self_attr, self_attr)
    assert {e for _, e, *_ in registry.scope_catalog()} == {"shop_a", "shop_b"}


def test_breakdowns_need_a_label_class(tmp_path) -> None:
    with pytest.raises(
        ValueError, match="'shop_orders' must declare breakdown_label_class"
    ):
        _load(tmp_path, _scoped_entity(label_class=None))


def test_label_class_must_be_known(tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown breakdown_label_class 'secret'"):
        _load(tmp_path, _scoped_entity(label_class="secret"))


def test_scope_catalog_lists_every_declared_dimension(tmp_path) -> None:
    registry = _load(
        tmp_path,
        _scoped_entity(
            dimensions=(
                "  sales_rep:\n    column: sales_rep\n    self: rep_name\n"
                "    description: The rep who closed the order\n"
                "  channel:\n    column: channel\n"
            )
        ),
    )

    assert registry.scope_catalog() == [
        ("testsrc", "shop", "channel", None, ""),
        ("testsrc", "shop", "sales_rep", "rep_name", "The rep who closed the order"),
    ]


def test_scope_catalog_is_empty_without_scoped_entities(tmp_path) -> None:
    registry = _load(tmp_path, _scoped_entity(dimensions="").replace(" {{scope}}", ""))
    assert registry.scope_catalog() == []


_QUERY_HEADS = {
    "metric": "SELECT COUNT(*) AS value FROM t WHERE TRUE",
    "breakdown": "SELECT channel AS label, COUNT(*) AS value FROM t WHERE TRUE",
    "funnel step": "SELECT COUNT(DISTINCT id) AS value FROM t WHERE TRUE",
    "freshness query": "SELECT MAX(created_at) FROM t WHERE TRUE",
}


@pytest.mark.parametrize("what", sorted(_QUERY_HEADS))
@pytest.mark.parametrize("scoped", [True, False])
def test_queries_may_not_use_the_reserved_scope_bind_prefix(
    tmp_path, what: str, scoped: bool
) -> None:
    yaml_text = _scoped_entity()
    if not scoped:
        yaml_text = _scoped_entity(dimensions="").replace(" {{scope}}", "")
    head = _QUERY_HEADS[what]
    assert yaml_text.count(head) == 1
    yaml_text = yaml_text.replace(head, f"{head} AND id = :scope_x")
    with pytest.raises(ValueError, match="reserved bind prefix :scope_"):
        _load(tmp_path, yaml_text)


def test_a_postgres_cast_to_a_scope_named_type_loads(tmp_path) -> None:
    yaml_text = _scoped_entity().replace(
        "SELECT COUNT(*) AS value FROM t WHERE TRUE",
        "SELECT COUNT(*) AS value FROM t WHERE channel::scope_enum IS NOT NULL",
        1,
    )
    assert "::scope_enum" in yaml_text
    assert _load(tmp_path, yaml_text).metrics["shop_orders"]


_QUERY_NAMES = {
    "metric": "metric 'shop_orders'",
    "breakdown": "breakdown of 'shop_orders'",
    "funnel step": "funnel 'shop_orders_funnel' step 'first'",
    "freshness query": "freshness query",
}


@pytest.mark.parametrize("what", sorted(_QUERY_HEADS))
@pytest.mark.parametrize(
    ("unsafe", "reason"),
    [
        (" OR id = 1 {{scope}}", "OR outside parentheses"),
        (" -- {{scope}}", "comment"),
        (' AND b = "{{scope}}"', "inside a quoted string"),
        (" {{scope}} UNION SELECT 1 FROM t", "UNION"),
        (" AND id IN (SELECT id FROM t WHERE TRUE {{scope}})", "inside parentheses"),
    ],
)
def test_unsafe_scope_placements_fail_the_load(
    tmp_path, what: str, unsafe: str, reason: str
) -> None:
    head = _QUERY_HEADS[what]
    yaml_text = _scoped_entity().replace(f"{head} {{{{scope}}}}", head + unsafe)
    assert yaml_text.count(unsafe) == 1
    with pytest.raises(ValueError, match=r"unsafe \{\{scope\}\} placement") as info:
        _load(tmp_path, yaml_text)
    message = str(info.value)
    assert f"{_QUERY_NAMES[what]} in testsrc:test.yaml" in message
    assert "entity 'shop'" in message
    assert reason in message


def test_unscoped_entities_are_not_placement_linted(tmp_path) -> None:
    yaml_text = _scoped_entity(dimensions="").replace(" {{scope}}", " OR id = 1")
    assert _load(tmp_path, yaml_text).metrics["shop_orders"]


def test_label_classes_come_from_the_masking_module() -> None:
    from app.atlas import masking  # noqa: PLC0415

    assert set(LABEL_CLASSES) == {masking.CATEGORY, *masking.CLEARANCE_FOR_CLASS}

"""Row-scope compiler: grants become bound predicates, never SQL text."""

from datetime import UTC, datetime, time, timedelta

import pytest

from app.atlas.scope import (
    MAX_SCOPE_ALTERNATIVES,
    MAX_SCOPE_BINDS,
    MAX_SCOPE_VALUES,
    SCOPE_TOKEN,
    UNDECLARED,
    CompiledScope,
    ScopeCompileError,
    compile_scope,
    narrow_scope,
    scope_placement_error,
    uses_reserved_bind,
)
from app.sources import get_connector
from app.sources.base import assert_read_only

QUERY = "SELECT SUM(amount) AS value FROM demo_orders WHERE TRUE {{scope}}"
COLUMNS = {"channel": "channel", "segment": "c.segment", "rep": "sales_rep"}


def test_unrestricted_compiles_to_and_true():
    compiled = compile_scope(QUERY, COLUMNS, None)

    assert compiled == CompiledScope(
        sql="SELECT SUM(amount) AS value FROM demo_orders WHERE TRUE AND TRUE",
        params={},
        restricted=False,
        dimensions=(),
        alternatives=(),
    )


def test_unrestricted_query_without_placeholder_is_unchanged():
    query = "SELECT 1 AS value"

    compiled = compile_scope(query, {}, None)

    assert compiled.sql == query
    assert compiled.restricted is False


def test_one_alternative():
    scope = ({"channel": frozenset({"b2c"})},)

    compiled = compile_scope(QUERY, COLUMNS, scope)

    assert compiled.sql.endswith("WHERE TRUE AND ((channel IN (:scope_0_0)))")
    assert compiled.params == {"scope_0_0": "b2c"}
    assert compiled.restricted is True
    assert compiled.dimensions == ("channel",)
    assert compiled.alternatives == scope


def test_values_within_a_dimension_are_sorted_into_one_in_list():
    scope = ({"channel": frozenset({"b2c", "b2b"})},)

    compiled = compile_scope(QUERY, COLUMNS, scope)

    assert compiled.sql.endswith("AND ((channel IN (:scope_0_0, :scope_0_1)))")
    assert compiled.params == {"scope_0_0": "b2b", "scope_0_1": "b2c"}


def test_two_alternatives_are_ored():
    scope = (
        {"channel": frozenset({"b2c"})},
        {"segment": frozenset({"corporate"})},
    )

    compiled = compile_scope(QUERY, COLUMNS, scope)

    assert compiled.sql.endswith(
        "AND ((channel IN (:scope_0_0)) OR (c.segment IN (:scope_1_0)))"
    )
    assert compiled.params == {"scope_0_0": "b2c", "scope_1_0": "corporate"}
    assert compiled.dimensions == ("channel", "segment")


def test_dimensions_in_one_alternative_are_anded():
    scope = (
        {"channel": frozenset({"b2c", "b2b"})},
        {"segment": frozenset({"corporate"}), "rep": frozenset({"Ana"})},
    )

    compiled = compile_scope(QUERY, COLUMNS, scope)

    assert compiled.sql.endswith(
        "AND ((channel IN (:scope_0_0, :scope_0_1)) OR "
        "((sales_rep IN (:scope_1_0)) AND (c.segment IN (:scope_1_1))))"
    )
    assert compiled.params == {
        "scope_0_0": "b2b",
        "scope_0_1": "b2c",
        "scope_1_0": "Ana",
        "scope_1_1": "corporate",
    }
    assert compiled.dimensions == ("channel", "rep", "segment")


def test_every_placeholder_gets_the_same_predicate():
    query = (
        "WITH a AS (SELECT 1 FROM demo_orders WHERE TRUE {{scope}}) "
        "SELECT COUNT(*) AS value FROM demo_orders WHERE TRUE {{scope}}"
    )
    scope = ({"channel": frozenset({"b2c"})},)

    compiled = compile_scope(query, COLUMNS, scope)

    assert SCOPE_TOKEN not in compiled.sql
    assert compiled.sql.count("AND ((channel IN (:scope_0_0)))") == 2
    assert compiled.params == {"scope_0_0": "b2c"}


def test_undeclared_dimensions_are_dropped():
    keep = {"channel": frozenset({"b2c"})}
    scope = ({"csm": frozenset({"Ana"}), "channel": frozenset({"b2b"})}, keep)

    assert narrow_scope(scope, {"channel": "channel"}) == (keep,)
    compiled = compile_scope(QUERY, {"channel": "channel"}, scope)
    assert compiled.alternatives == (keep,)
    assert compiled.params == {"scope_0_0": "b2c"}


def test_narrow_scope_passes_unrestricted_through():
    assert narrow_scope(None, COLUMNS) is None


def test_dropping_everything_raises():
    scope = ({"csm": frozenset({"Ana"})},)

    with pytest.raises(ScopeCompileError, match=UNDECLARED):
        narrow_scope(scope, COLUMNS)
    with pytest.raises(ScopeCompileError, match=UNDECLARED):
        compile_scope(QUERY, COLUMNS, scope)


def test_empty_scope_raises():
    with pytest.raises(ScopeCompileError):
        narrow_scope((), COLUMNS)
    with pytest.raises(ScopeCompileError):
        compile_scope(QUERY, COLUMNS, ())


def test_too_many_values_raises():
    values = frozenset(f"v{i}" for i in range(MAX_SCOPE_VALUES + 1))

    with pytest.raises(ScopeCompileError):
        compile_scope(QUERY, COLUMNS, ({"channel": values},))


def test_exactly_the_value_cap_compiles():
    values = frozenset(f"v{i:03d}" for i in range(MAX_SCOPE_VALUES))

    compiled = compile_scope(QUERY, COLUMNS, ({"channel": values},))

    assert len(compiled.params) == MAX_SCOPE_VALUES


@pytest.mark.parametrize(
    "alternative",
    [{}, {"channel": frozenset()}],
    ids=["empty-alternative", "empty-values"],
)
def test_empty_alternatives_or_value_sets_fail_closed(alternative):
    with pytest.raises(ScopeCompileError):
        compile_scope(QUERY, COLUMNS, (alternative,))


def test_non_string_values_fail_closed():
    scope = ({"channel": frozenset({1})},)

    with pytest.raises(ScopeCompileError):
        compile_scope(QUERY, COLUMNS, scope)  # pyright: ignore[reportArgumentType]


def test_query_without_placeholder_and_a_scope_raises():
    scope = ({"channel": frozenset({"b2c"})},)

    with pytest.raises(ScopeCompileError):
        compile_scope("SELECT 1 AS value FROM demo_orders", COLUMNS, scope)


@pytest.mark.parametrize(
    "column",
    ["x; drop table demo_orders", "a.b.c", "1col", "channel\n", "(channel)", ""],
)
def test_unsafe_column_text_is_rejected(column):
    scope = ({"channel": frozenset({"b2c"})},)

    with pytest.raises(ScopeCompileError):
        compile_scope(QUERY, {"channel": column}, scope)


ADVERSARIAL = [
    "' OR 1=1 --",
    "'); DROP TABLE demo_orders; --",
    "ü-Ünïcødé 名前",
    ":limit",
    "{{scope}}",
]


@pytest.mark.parametrize("value", ADVERSARIAL)
def test_adversarial_values_only_ever_reach_params(value):
    scope = (
        {"channel": frozenset({value, "b2c"})},
        {"segment": frozenset({value}), "rep": frozenset({value})},
    )

    compiled = compile_scope(QUERY, COLUMNS, scope)

    assert value not in compiled.sql
    assert value in compiled.params.values()
    assert set(compiled.params) == {
        "scope_0_0",
        "scope_0_1",
        "scope_1_0",
        "scope_1_1",
    }
    assert_read_only(compiled.sql)


@pytest.mark.parametrize("key", ["channel) OR (1=1", "'; DROP TABLE x; --"])
def test_adversarial_dimension_keys_never_reach_sql(key):
    scope = ({key: frozenset({"b2c"})}, {"channel": frozenset({"b2b"})})

    compiled = compile_scope(QUERY, COLUMNS, scope)

    assert key not in compiled.sql
    assert compiled.alternatives == ({"channel": frozenset({"b2b"})},)


def _last_seven_full_days() -> dict[str, datetime]:
    today = datetime.now(UTC).date()
    return {
        "start": datetime.combine(today - timedelta(days=7), time.min, tzinfo=UTC),
        "end": datetime.combine(today - timedelta(days=1), time.max, tzinfo=UTC),
    }


REVENUE = (
    "SELECT COALESCE(SUM(amount), 0) AS value FROM demo_orders "
    "WHERE status = 'paid' AND created_at >= :start AND created_at <= :end "
    "{{scope}}"
)


async def test_compiled_sql_runs_on_sqlite(db):
    connector = get_connector("demo")
    params = _last_seven_full_days()

    scoped = compile_scope(REVENUE, COLUMNS, ({"channel": frozenset({"b2c"})},))
    row = await connector.fetch_one(scoped.sql, params | scoped.params)
    assert row is not None
    assert float(row["value"]) == 3500.0

    unrestricted = compile_scope(REVENUE, COLUMNS, None)
    row = await connector.fetch_one(unrestricted.sql, params | unrestricted.params)
    assert row is not None
    assert float(row["value"]) == 10500.0


async def test_injection_values_match_no_rows_on_sqlite(db):
    connector = get_connector("demo")
    scope = ({"channel": frozenset(ADVERSARIAL)},)

    compiled = compile_scope(REVENUE, COLUMNS, scope)
    row = await connector.fetch_one(
        compiled.sql, _last_seven_full_days() | compiled.params
    )

    assert row is not None
    assert float(row["value"]) == 0.0
    total = await connector.fetch_one("SELECT COUNT(*) AS value FROM demo_orders", {})
    assert total is not None
    assert total["value"] > 0


@pytest.mark.parametrize("values", ["b2c", b"b2c"], ids=["str", "bytes"])
def test_a_bare_string_value_set_is_rejected_not_split(values):
    scope = ({"channel": values},)

    with pytest.raises(ScopeCompileError, match="set of strings"):
        compile_scope(QUERY, COLUMNS, scope)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    "scope",
    [("channel",), ([("channel", frozenset({"b2c"}))],), ({1: frozenset({"b2c"})},)],
    ids=["str-alternative", "list-alternative", "non-str-key"],
)
def test_malformed_alternatives_raise_a_compile_error(scope):
    with pytest.raises(ScopeCompileError):
        narrow_scope(scope, COLUMNS)  # pyright: ignore[reportArgumentType]


def test_too_many_alternatives_raises():
    scope = tuple(
        {"channel": frozenset({f"v{i}"})} for i in range(MAX_SCOPE_ALTERNATIVES + 1)
    )

    with pytest.raises(ScopeCompileError):
        compile_scope(QUERY, COLUMNS, scope)


def test_too_many_binds_in_total_raises():
    per_alt = MAX_SCOPE_VALUES
    count = MAX_SCOPE_BINDS // per_alt + 1
    assert count <= MAX_SCOPE_ALTERNATIVES
    scope = tuple(
        {"channel": frozenset(f"a{i}v{j}" for j in range(per_alt))}
        for i in range(count)
    )

    with pytest.raises(ScopeCompileError):
        compile_scope(QUERY, COLUMNS, scope)


def test_a_query_using_the_reserved_bind_prefix_is_rejected():
    query = "SELECT 1 AS value FROM demo_orders WHERE id = :scope_x {{scope}}"

    with pytest.raises(ScopeCompileError):
        compile_scope(query, COLUMNS, ({"channel": frozenset({"b2c"})},))
    with pytest.raises(ScopeCompileError):
        compile_scope(query, COLUMNS, None)


def test_a_postgres_cast_to_a_scope_named_type_is_not_a_reserved_bind():
    query = (
        "SELECT COUNT(*) AS value FROM demo_orders "
        "WHERE channel::scope_enum IS NOT NULL {{scope}}"
    )

    compiled = compile_scope(query, COLUMNS, ({"channel": frozenset({"b2c"})},))

    assert compiled.params == {"scope_0_0": "b2c"}


@pytest.mark.parametrize(
    ("sql", "reserved"),
    [
        ("WHERE id = :scope_x", True),
        ("WHERE id=:scope_0_0", True),
        ("WHERE channel::scope_enum = 'b2c'", False),
        ("WHERE id = :start AND scope_x = 1", False),
        ("WHERE TRUE {{scope}}", False),
    ],
)
def test_uses_reserved_bind(sql: str, reserved: bool):
    assert uses_reserved_bind(sql) is reserved


def test_compiled_alternatives_are_frozen_copies():
    values = {"b2c"}
    alternative = {"channel": values}

    compiled = compile_scope(QUERY, COLUMNS, (alternative,))  # pyright: ignore[reportArgumentType]
    alternative["segment"] = frozenset({"corporate"})  # pyright: ignore[reportArgumentType]
    values.add("b2b")

    assert compiled.alternatives == ({"channel": frozenset({"b2c"})},)
    with pytest.raises(TypeError):
        compiled.alternatives[0]["channel"] = frozenset()  # pyright: ignore[reportIndexIssue]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) FROM t WHERE created_at >= :start {{scope}}",
        "SELECT COUNT(*) FROM t WHERE TRUE {{scope}}",
        "SELECT COUNT(*) FROM t WHERE (a = 1 OR b = 2) {{scope}}",
        "SELECT COUNT(*) FROM t WHERE x::scope_enum = 'b2c' {{scope}}",
        "SELECT COUNT(*) FROM t WHERE stage IN ('a', 'b') {{scope}} GROUP BY c",
        "SELECT 'it''s -- not a comment' AS v FROM t WHERE TRUE {{scope}}",
        'SELECT "OR" AS v FROM t WHERE TRUE {{scope}}',
        "SELECT orders, ORDER_id FROM t WHERE TRUE {{scope}}",
        "SELECT a FROM t WHERE TRUE {{scope}} AND b = 1 {{scope}}",
        "SELECT a FROM t WHERE TRUE {{scope}} GROUP BY a ORDER BY a LIMIT :limit",
        "SELECT a FROM t WHERE (d BETWEEN :start AND :end) {{scope}}",
        "WITH c AS (SELECT * FROM t WHERE a OR b) SELECT a FROM c WHERE TRUE {{scope}}",
    ],
)
def test_safe_scope_placements_are_accepted(sql: str):
    assert scope_placement_error(sql) is None


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT a FROM t WHERE a = 1 OR b = 2 {{scope}}", "OR outside parentheses"),
        ("SELECT a FROM t WHERE a = 1 or b = 2 {{scope}}", "OR outside parentheses"),
        ("SELECT a FROM t WHERE TRUE {{scope}} OR b = 2", "OR outside parentheses"),
        ("SELECT a FROM t WHERE TRUE -- {{scope}}", "comment"),
        ("SELECT a FROM t WHERE TRUE /* {{scope}} */", "comment"),
        ("SELECT a FROM t WHERE TRUE {{scope}} -- note", "comment"),
        ("SELECT a FROM t WHERE TRUE {{scope}} UNION SELECT a FROM u", "UNION"),
        ("SELECT a FROM t WHERE TRUE {{scope}} intersect SELECT a FROM u", "INTERSECT"),
        ("SELECT a FROM t WHERE TRUE {{scope}} EXCEPT SELECT a FROM u", "EXCEPT"),
        ("SELECT a FROM t WHERE b = '{{scope}}'", "inside a quoted string"),
        ('SELECT a FROM t WHERE b = "{{scope}}"', "inside a quoted string"),
        (
            "SELECT a FROM t WHERE b IN (SELECT c FROM u WHERE TRUE {{scope}})",
            "inside parentheses",
        ),
        ("SELECT a FROM t WHERE b = 'open {{scope}}", "unterminated"),
        # The token must sit at the top level of WHERE, before AND or a clause.
        ("SELECT a FROM t LEFT JOIN u ON t.id = u.id {{scope}}", "WHERE clause"),
        ("SELECT a FROM t WHERE TRUE {{scope}} IS NOT TRUE", "WHERE clause"),
        ("SELECT a FROM t WHERE TRUE {{scope}} = FALSE", "WHERE clause"),
        ("SELECT a FROM t WHERE TRUE GROUP BY a {{scope}}", "WHERE clause"),
        ("SELECT a FROM t WHERE TRUE ORDER BY a {{scope}}", "WHERE clause"),
        ("SELECT a FROM t WHERE TRUE HAVING a {{scope}}", "WHERE clause"),
        ("SELECT COUNT(*) {{scope}} FROM t", "WHERE clause"),
        ("SELECT a FROM t {{scope}} WHERE TRUE", "WHERE clause"),
        # Postgres string forms this reader does not parse fail closed.
        (r"SELECT a FROM t WHERE a = E'\'' OR TRUE OR b = E'\'' {{scope}}", "prefixed"),
        ("SELECT a FROM t WHERE b = U&'x' {{scope}}", "prefixed"),
        ("SELECT a FROM t WHERE b = $$ {{scope}} $$", "dollar quote"),
        ("SELECT a FROM t WHERE b = $q$ {{scope}} $q$", "dollar quote"),
        ("SELECT a FROM t WHERE TRUE {{scope}}; SELECT 1", "statement separator"),
        ("SELECT a FROM t WHERE x) OR (y {{scope}}", "unbalanced"),
        ("SELECT a FROM t WHERE (x {{scope}}", "unbalanced"),
        ("SELECT a FROM t WHERE f BETWEEN FALSE {{scope}} AND TRUE", "BETWEEN"),
        ("SELECT a FROM t WHERE f between symmetric 0 {{scope}} AND 1", "BETWEEN"),
    ],
)
def test_unsafe_scope_placements_are_rejected(sql: str, reason: str):
    error = scope_placement_error(sql)

    assert error is not None
    assert reason in error

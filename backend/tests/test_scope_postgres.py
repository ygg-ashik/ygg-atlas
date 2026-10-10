"""Row scope on real PostgreSQL: compiled ``IN (:scope_i_j)`` binds run via asyncpg.

The scope compiler's output is otherwise only executed on SQLite. asyncpg
rewrites named binds to ``$n`` positional parameters, so this proves the
compiled predicate filters correctly there and that grant values stay literals.

The rows live in a TEMP table on one connection: Postgres drops it when the
connection closes, so nothing is left behind in the shared TEST_PG_URL schema.

Opt-in: set TEST_PG_URL to an empty, disposable database, e.g.
postgresql+asyncpg://atlas:atlas@localhost:55436/scratch.
"""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.atlas.scope import RowScope, compile_scope
from tests.pg_guard import PG_XDIST_GROUP, is_disposable

PG_URL = os.environ.get("TEST_PG_URL", "")

pytestmark = [
    pytest.mark.skipif(
        not is_disposable(PG_URL),
        reason="TEST_PG_URL not set, or its database name lacks 'test'/'scratch'",
    ),
    # The other PG modules reset the TEST_PG_URL schema: share their worker.
    pytest.mark.xdist_group(PG_XDIST_GROUP),
]

QUERY = "SELECT COUNT(*) AS value FROM scope_orders WHERE TRUE {{scope}}"
COLUMNS = {"channel": "channel", "rep": "sales_rep"}
ROWS = [
    ("b2c", "Aisha"),
    ("b2c", "Omar"),
    ("b2b", "Aisha"),
    ("b2b", "Lina"),
    ("b2b", "Omar"),
    ("gift", "Lina"),
]


@pytest.fixture
async def conn() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(PG_URL)
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    "CREATE TEMP TABLE scope_orders"
                    " (id SERIAL PRIMARY KEY, channel TEXT, sales_rep TEXT)"
                    " ON COMMIT PRESERVE ROWS"
                )
            )
            await connection.execute(
                text("INSERT INTO scope_orders (channel, sales_rep) VALUES (:c, :r)"),
                [{"c": channel, "r": rep} for channel, rep in ROWS],
            )
            yield connection
            await connection.rollback()
    finally:
        await engine.dispose()


async def _count(conn: AsyncConnection, scope: RowScope | None) -> int:
    compiled = compile_scope(QUERY, COLUMNS, scope)
    result = await conn.execute(text(compiled.sql), compiled.params)
    return int(result.scalar_one())


async def test_unrestricted_scope_counts_every_row(conn: AsyncConnection) -> None:
    assert await _count(conn, None) == len(ROWS)


async def test_alternatives_or_and_values_in_on_postgres(
    conn: AsyncConnection,
) -> None:
    scope: RowScope = (
        {"channel": frozenset({"b2c"})},
        {"rep": frozenset({"Lina", "Omar"})},
    )
    compiled = compile_scope(QUERY, COLUMNS, scope)
    assert compiled.params == {
        "scope_0_0": "b2c",
        "scope_1_0": "Lina",
        "scope_1_1": "Omar",
    }

    # b2c (2 rows) OR rep in {Lina, Omar} (4 rows); b2c/Omar overlaps once.
    assert await _count(conn, scope) == 5


async def test_dimensions_inside_one_alternative_are_anded(
    conn: AsyncConnection,
) -> None:
    scope: RowScope = ({"channel": frozenset({"b2b"}), "rep": frozenset({"Aisha"})},)

    assert await _count(conn, scope) == 1


async def test_sql_metacharacters_in_a_value_stay_literal(
    conn: AsyncConnection,
) -> None:
    injection = "x' OR '1'='1"
    scope: RowScope = ({"channel": frozenset({injection, "x'); DROP TABLE t; --"})},)

    assert await _count(conn, scope) == 0
    # A literal match still works, so the bind really carried the raw value.
    await conn.execute(
        text("INSERT INTO scope_orders (channel, sales_rep) VALUES (:c, 'Eve')"),
        {"c": injection},
    )
    assert await _count(conn, scope) == 1
    assert await _count(conn, None) == len(ROWS) + 1

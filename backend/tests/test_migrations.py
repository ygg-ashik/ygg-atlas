"""Temporary startup ALTER for chat_messages.blocks (until the Alembic baseline)."""

from app.models.migrations import ensure_blocks_column

BLOCKS_DDL = "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS blocks JSON"


class _Dialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _Conn:
    def __init__(self, dialect: str) -> None:
        self.dialect = _Dialect(dialect)
        self.sql: list[str] = []

    async def execute(self, statement: object) -> None:
        self.sql.append(str(statement))


async def test_postgres_adds_blocks_column_idempotently():
    conn = _Conn("postgresql")
    await ensure_blocks_column(conn)
    assert conn.sql == [BLOCKS_DDL]


async def test_sqlite_is_a_noop_because_create_all_builds_fresh_schemas():
    conn = _Conn("sqlite")
    await ensure_blocks_column(conn)
    assert conn.sql == []

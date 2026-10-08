"""Startup schema patch for databases created before `chat_messages.blocks` existed.

The MVP builds its schema with `SQLModel.metadata.create_all`, which never alters
existing tables, so the nullable `blocks` column is added here.
"""

from typing import Protocol

from sqlalchemy import TextClause, text

# Temporary until the Alembic baseline (auth-rbac phase 1) replaces
# create_all + this ALTER.
_BLOCKS_DDL = "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS blocks JSON"


class _Dialect(Protocol):
    @property
    def name(self) -> str: ...


class DDLConnection(Protocol):
    """The parts of `AsyncConnection` this patch uses (fakeable in tests)."""

    @property
    def dialect(self) -> _Dialect: ...

    async def execute(self, statement: TextClause, /) -> object: ...


async def ensure_blocks_column(conn: DDLConnection) -> None:
    """Add `chat_messages.blocks` on Postgres (idempotent).

    sqlite is a no-op: it only backs fresh test schemas, which create_all builds
    with every column already present.
    """
    if conn.dialect.name != "postgresql":
        return
    await conn.execute(text(_BLOCKS_DDL))

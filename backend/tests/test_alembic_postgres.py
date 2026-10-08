"""Migrations on real PostgreSQL (the production path). Opt-in: set TEST_PG_URL to an
empty, disposable database, e.g. postgresql+asyncpg://atlas:atlas@localhost:5434/scratch.
"""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel

import app.identity.models  # registers users on the metadata
import app.models  # noqa: F401  # registers chat and audit tables

PG_URL = os.environ.get("TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="TEST_PG_URL not set")

BACKEND = Path(__file__).parents[1]


def _config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", PG_URL)
    return config


async def _upgrade(target: str) -> None:
    # env.py runs its own event loop, so Alembic must run off this one.
    await asyncio.to_thread(command.upgrade, _config(), target)


def _drift(conn: Connection) -> list[object]:
    return list(compare_metadata(MigrationContext.configure(conn), SQLModel.metadata))


async def _reset(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.text("DROP SCHEMA public CASCADE"))
        await conn.execute(sa.text("CREATE SCHEMA public"))


@pytest.fixture
async def engine():
    engine = create_async_engine(PG_URL)
    await _reset(engine)
    yield engine
    await _reset(engine)
    await engine.dispose()


async def test_head_on_empty_postgres_has_no_drift(engine: AsyncEngine) -> None:
    await _upgrade("head")
    async with engine.connect() as conn:
        assert await conn.run_sync(_drift) == []


async def test_legacy_create_all_database_upgrades_in_place(
    engine: AsyncEngine,
) -> None:
    # Recreate the pre-Alembic EC2 shape: baseline tables, no blocks, no version row.
    await _upgrade("0001")
    async with engine.begin() as conn:
        await conn.execute(sa.text("ALTER TABLE chat_messages DROP COLUMN blocks"))
        await conn.execute(sa.text("DROP TABLE alembic_version"))
        for uid, email in [
            ("fb-sara", "Sara@yougotagift.com"),
            ("fb-sara", ""),
            ("dev-user", "dev@yougotagift.com"),
        ]:
            await conn.execute(
                sa.text(
                    "INSERT INTO chat_sessions VALUES "
                    "(:id, :uid, :email, 't', now(), now())"
                ),
                {"id": uuid4(), "uid": uid, "email": email},
            )

    await _upgrade("head")

    async with engine.connect() as conn:
        assert await conn.run_sync(_drift) == []
        users = (
            await conn.execute(sa.text("SELECT email, firebase_uid FROM users"))
        ).all()
        unlinked = (
            await conn.execute(
                sa.text("SELECT count(*) FROM chat_sessions WHERE user_id IS NULL")
            )
        ).scalar_one()
    assert sorted(users) == [
        ("dev@yougotagift.com", None),
        ("sara@yougotagift.com", "fb-sara"),
    ]
    assert unlinked == 0

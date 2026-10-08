"""Startup capability sync on real PostgreSQL: concurrent processes must not race.

Opt-in: set TEST_PG_URL to an empty, disposable database, e.g.
postgresql+asyncpg://atlas:atlas@localhost:55436/scratch.
"""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import select

from app.access.catalog import CAPABILITIES
from app.access.models import Capability, PolicyState
from app.access.startup import prepare_access

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


async def _reset(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture
async def engine():
    engine = create_async_engine(PG_URL)
    await _reset(engine)
    yield engine
    await _reset(engine)
    await engine.dispose()


async def test_concurrent_prepare_access_does_not_race(engine: AsyncEngine) -> None:
    await _upgrade("head")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _run() -> None:
        async with factory() as db:
            await prepare_access(db)

    await asyncio.gather(_run(), _run())

    async with factory() as db:
        rows = (await db.execute(select(Capability))).scalars().all()
        state = await db.get(PolicyState, 1, populate_existing=True)

    assert len(rows) == len(CAPABILITIES)
    assert state is not None
    # 1 seeded by the migration, plus one bump per concurrent prepare_access call.
    assert state.policy_version == 3

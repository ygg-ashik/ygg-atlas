"""Access on real PostgreSQL: concurrent startup syncs and admin writes must not race.

Admin writes serialize on a `policy_state` row lock (`lock_for_write`), which
SQLite drops, so only these tests prove it: each concurrent caller gets its own
session and its own AccessAdmin, as separate API requests would.

Opt-in: set TEST_PG_URL to an empty, disposable database, e.g.
postgresql+asyncpg://atlas:atlas@localhost:55436/scratch.
"""

import asyncio
import contextlib
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import col, func, select

from app.access.admin import Actor
from app.access.catalog import CAPABILITIES
from app.access.errors import AccessError, ConflictError
from app.access.models import Capability, Group, PolicyState, RbacChange
from app.access.repository import AccessRepository
from app.access.schemas import GroupCreate, GroupUpdate
from app.access.startup import prepare_access
from tests.access_helpers import admin_for, policy_version
from tests.pg_guard import is_disposable

PG_URL = os.environ.get("TEST_PG_URL", "")

pytestmark = pytest.mark.skipif(
    not is_disposable(PG_URL),
    reason="TEST_PG_URL not set, or its database name lacks 'test'/'scratch'",
)

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


@pytest.fixture
async def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """A migrated database; one session per concurrent caller."""
    await _upgrade("head")
    return async_sessionmaker(engine, expire_on_commit=False)


def _widen_race(monkeypatch: pytest.MonkeyPatch, method: str, parties: int = 2) -> None:
    """Hold each caller at `AccessRepository.<method>` (the read behind an
    application-level check) until all `parties` arrive, or 0.5s pass.

    Without the policy_state lock every caller reaches the check before any
    commits, so a check-then-write race is certain, not timing luck. With it,
    the lock holder times out alone and commits before the next caller even
    gets to the check.
    """
    original = getattr(AccessRepository, method)
    arrived = 0
    everyone = asyncio.Event()

    async def held(self: AccessRepository, *args: object, **kwargs: object) -> object:
        nonlocal arrived
        arrived += 1
        if arrived >= parties:
            everyone.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(everyone.wait(), 0.5)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AccessRepository, method, held)


async def _create_group(factory: async_sessionmaker[AsyncSession], name: str) -> Group:
    async with factory() as db:
        return await admin_for(db).create_group(Actor.cli(), GroupCreate(name=name))


async def _move_group(
    factory: async_sessionmaker[AsyncSession], group: Group, parent: Group
) -> Group:
    async with factory() as db:
        return await admin_for(db).update_group(
            Actor.cli(), group.id, GroupUpdate(parent_id=parent.id)
        )


async def _counts(factory: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    """(policy_version, rbac_changes rows) as committed."""
    async with factory() as db:
        changes = (await db.execute(select(func.count()).select_from(RbacChange))).one()
        return await policy_version(db), changes[0]


async def test_concurrent_create_same_group_name_conflicts_cleanly(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    start_version, start_changes = await _counts(factory)
    _widen_race(monkeypatch, "group_by_name")

    results = await asyncio.gather(
        _create_group(factory, "finance"),
        _create_group(factory, "finance"),
        return_exceptions=True,
    )

    created = [r for r in results if isinstance(r, Group)]
    errors = [r for r in results if isinstance(r, BaseException)]
    assert len(created) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ConflictError)  # a 409, never an IntegrityError/500
    async with factory() as db:
        rows = (
            await db.execute(select(Group).where(col(Group.name) == "finance"))
        ).all()
    assert len(rows) == 1
    assert await _counts(factory) == (start_version + 1, start_changes + 1)


async def test_concurrent_crossing_moves_cannot_make_a_cycle(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    a = await _create_group(factory, "a")
    b = await _create_group(factory, "b")
    _widen_race(monkeypatch, "tenant_groups")

    results = await asyncio.gather(
        _move_group(factory, a, b), _move_group(factory, b, a), return_exceptions=True
    )

    moved = [r for r in results if isinstance(r, Group)]
    errors = [r for r in results if isinstance(r, BaseException)]
    assert len(moved) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], AccessError)
    async with factory() as db:
        groups = {
            g.id: g.parent_id for g in (await db.execute(select(Group))).scalars()
        }
    for start, parent in groups.items():
        seen: set[object] = set()
        current = parent
        while current is not None:
            assert current != start, "the group tree has a cycle"
            assert current not in seen
            seen.add(current)
            current = groups[current]


async def test_concurrent_admin_writes_lose_no_version_bump(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    start_version, start_changes = await _counts(factory)
    _widen_race(monkeypatch, "group_by_name", parties=5)

    results = await asyncio.gather(
        *(_create_group(factory, f"team-{i}") for i in range(5)),
        return_exceptions=True,
    )

    succeeded = sum(isinstance(r, Group) for r in results)
    assert succeeded == 5, results
    assert await _counts(factory) == (
        start_version + succeeded,
        start_changes + succeeded,
    )

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
from uuid import UUID

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
from app.access.errors import AccessError, ConflictError, InvalidChangeError
from app.access.models import (
    AccessRequest,
    Capability,
    Grant,
    Group,
    GroupMember,
    PolicyState,
    RbacChange,
)
from app.access.repository import AccessRepository
from app.access.schemas import (
    AccessRequestCreate,
    AccessRequestOut,
    GroupCreate,
    GroupUpdate,
    RequestDecision,
)
from app.access.startup import prepare_access
from app.identity.models import User
from tests.access_helpers import admin_for, policy_of, policy_version, requests_for
from tests.pg_guard import PG_XDIST_GROUP, is_disposable

PG_URL = os.environ.get("TEST_PG_URL", "")

pytestmark = [
    pytest.mark.skipif(
        not is_disposable(PG_URL),
        reason="TEST_PG_URL not set, or its database name lacks 'test'/'scratch'",
    ),
    # Both PG modules reset the one TEST_PG_URL schema: one xdist worker runs them.
    pytest.mark.xdist_group(PG_XDIST_GROUP),
]

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


# ---- access requests (phase 5) ------------------------------------------------


async def _requester(factory: async_sessionmaker[AsyncSession]) -> UUID:
    async with factory() as db:
        user = User(email="sara@yougotagift.com")
        db.add(user)
        await db.commit()
        return user.id


async def _ask(
    factory: async_sessionmaker[AsyncSession], user_id: UUID, kind: str, target: str
) -> AccessRequestOut:
    async with factory() as db:
        user = await db.get(User, user_id)
        assert user is not None
        payload = AccessRequestCreate.model_validate(
            {"kind": kind, "target": target, "note": "please"}
        )
        return await requests_for(db).create(await policy_of(db, user), payload)


async def _approve(
    factory: async_sessionmaker[AsyncSession], request_id: UUID
) -> AccessRequestOut:
    async with factory() as db:
        return await requests_for(db).approve(
            Actor.cli(), request_id, RequestDecision()
        )


async def test_concurrent_approvals_exactly_one_wins(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two CLI actors (no stale-actor check): the locked re-read is what holds."""
    group = await _create_group(factory, "growth")
    sara = await _requester(factory)
    request = await _ask(factory, sara, "group", str(group.id))
    start_version, start_changes = await _counts(factory)
    _widen_race(monkeypatch, "request")  # both pass the pre-lock read

    results = await asyncio.gather(
        _approve(factory, request.id),
        _approve(factory, request.id),
        return_exceptions=True,
    )

    approved = [r for r in results if isinstance(r, AccessRequestOut)]
    errors = [r for r in results if isinstance(r, BaseException)]
    assert len(approved) == 1, results
    assert len(errors) == 1
    assert isinstance(errors[0], ConflictError)
    assert await _counts(factory) == (start_version + 1, start_changes + 2)
    async with factory() as db:
        members = (await db.execute(select(GroupMember))).scalars().all()
    assert [(m.group_id, m.user_id) for m in members] == [(group.id, sara)]


async def test_cancel_racing_an_approval_one_wins(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    sara = await _requester(factory)
    request = await _ask(factory, sara, "resource", "demo/order/revenue")
    _widen_race(monkeypatch, "request")  # approve and cancel both read first

    async def _cancel() -> AccessRequestOut:
        async with factory() as db:
            user = await db.get(User, sara)
            assert user is not None
            return await requests_for(db).cancel(await policy_of(db, user), request.id)

    results = await asyncio.gather(
        _approve(factory, request.id), _cancel(), return_exceptions=True
    )

    wins = [r for r in results if isinstance(r, AccessRequestOut)]
    errors = [r for r in results if isinstance(r, BaseException)]
    assert len(wins) == 1, results
    assert len(errors) == 1
    assert isinstance(errors[0], ConflictError)
    async with factory() as db:
        row = await db.get(AccessRequest, request.id, populate_existing=True)
        grants = (await db.execute(select(Grant))).scalars().all()
    assert row is not None
    assert row.status == wins[0].status
    assert len(grants) == (1 if row.status == "approved" else 0)


async def test_concurrent_creates_respect_the_cap(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    sara = await _requester(factory)
    for i in range(19):
        await _ask(factory, sara, "resource", f"demo/order/m{i}")
    _widen_race(monkeypatch, "count_pending")

    results = await asyncio.gather(
        _ask(factory, sara, "resource", "demo/order/a"),
        _ask(factory, sara, "resource", "demo/order/b"),
        return_exceptions=True,
    )

    created = [r for r in results if isinstance(r, AccessRequestOut)]
    errors = [r for r in results if isinstance(r, BaseException)]
    assert len(created) == 1, results
    assert len(errors) == 1
    assert isinstance(errors[0], InvalidChangeError)
    async with factory() as db:
        pending = (
            await db.execute(
                select(func.count())
                .select_from(AccessRequest)
                .where(col(AccessRequest.status) == "pending")
            )
        ).one()[0]
    assert pending == 20

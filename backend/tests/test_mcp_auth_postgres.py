"""OAuth single-use guarantees on real PostgreSQL (D5, D6, D30, D36).

Every "only once" write is a conditional UPDATE; on READ COMMITTED the loser waits
for the winner's row lock, re-checks its WHERE clause and matches 0 rows. SQLite
serialises writers, so only these tests prove it: each concurrent caller gets its
own session and its own OAuthService, as separate HTTP requests would.

Opt-in: set TEST_PG_URL to an empty, disposable database, e.g.
postgresql+asyncpg://atlas:atlas@localhost:55436/scratch.
"""

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
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
from sqlmodel import col, select

from app.identity.api_tokens import (
    EVENT_REFRESH_GRACE,
    EVENT_REFRESHED,
    EVENT_REUSE_DETECTED,
    REVOKED_CODE_REUSE,
)
from app.identity.models import ApiToken, CredentialEvent, OAuthCode, User
from app.identity.oauth import (
    AuthorizationRequestNotFoundError,
    CodeGrant,
    OAuthGrantError,
    OAuthService,
    RefreshGrant,
    TokenPair,
)
from app.identity.repository import CredentialRepository
from tests.identity.credential_helpers import make_client
from tests.identity.oauth_helpers import (
    always_eligible,
    approved_code,
    begin,
    oauth_config,
)
from tests.pg_guard import PG_XDIST_GROUP, is_disposable

PG_URL = os.environ.get("TEST_PG_URL", "")

pytestmark = [
    pytest.mark.skipif(
        not is_disposable(PG_URL),
        reason="TEST_PG_URL not set, or its database name lacks 'test'/'scratch'",
    ),
    # Every PG module resets the one TEST_PG_URL schema: one xdist worker runs them.
    pytest.mark.xdist_group(PG_XDIST_GROUP),
]

BACKEND = Path(__file__).parents[1]
Factory = async_sessionmaker[AsyncSession]


def _config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", PG_URL)
    return config


async def _reset(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture
async def factory() -> AsyncIterator[Factory]:
    engine = create_async_engine(PG_URL)
    await _reset(engine)
    # env.py runs its own event loop, so Alembic must run off this one.
    await asyncio.to_thread(command.upgrade, _config(), "head")
    yield async_sessionmaker(engine, expire_on_commit=False)
    await _reset(engine)
    await engine.dispose()


@pytest.fixture
async def setup(factory: Factory) -> tuple[User, str]:
    async with factory() as db:
        user = User(email="alice@yougotagift.com")
        db.add(user)
        await db.commit()
        client = await make_client(db)
        return user, client.client_id


def _hold_until_both_arrive(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    """Hold each caller at `CredentialRepository.<method>` (the single-use UPDATE)
    until both arrive, or 0.5 s pass, so the two UPDATEs really do race on the row
    lock instead of running one after the other."""
    original = getattr(CredentialRepository, method)
    arrived = 0
    both = asyncio.Event()

    async def held(self: CredentialRepository, *args: object) -> object:
        nonlocal arrived
        arrived += 1
        if arrived >= 2:
            both.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(both.wait(), 0.5)
        return await original(self, *args)

    monkeypatch.setattr(CredentialRepository, method, held)


def _service(db: AsyncSession) -> OAuthService:
    return OAuthService(db, oauth_config())


async def _events(factory: Factory, event: str) -> list[CredentialEvent]:
    async with factory() as db:
        result = await db.execute(
            select(CredentialEvent).where(col(CredentialEvent.event) == event)
        )
        return list(result.scalars().all())


async def _exchange(factory: Factory, client_id: str, grant: CodeGrant) -> TokenPair:
    async with factory() as db:
        return await _service(db).exchange_code(client_id, grant, always_eligible)


async def _rotate(factory: Factory, client_id: str, grant: RefreshGrant) -> TokenPair:
    async with factory() as db:
        return await _service(db).rotate_refresh(client_id, grant, always_eligible)


async def _approve(factory: Factory, txn: str, user: User) -> str:
    async with factory() as db:
        return await _service(db).approve(txn, user.id)


async def test_concurrent_code_exchange_exactly_one_wins(
    factory: Factory, setup: tuple[User, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    user, client_id = setup
    async with factory() as db:
        _, grant = await approved_code(_service(db), user, client_id)
    _hold_until_both_arrive(monkeypatch, "mark_code_used")

    results = await asyncio.gather(
        _exchange(factory, client_id, grant),
        _exchange(factory, client_id, grant),
        return_exceptions=True,
    )

    pairs = [r for r in results if isinstance(r, TokenPair)]
    errors = [r for r in results if isinstance(r, BaseException)]
    assert len(pairs) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], OAuthGrantError)
    async with factory() as db:
        family = (
            (
                await db.execute(
                    select(ApiToken).where(col(ApiToken.family_id) == grant.family_id)
                )
            )
            .scalars()
            .all()
        )
    assert len(family) == 2  # the winner's pair (C8: revoked as reuse)
    assert {row.revoked_reason for row in family} == {REVOKED_CODE_REUSE}
    assert len(await _events(factory, EVENT_REUSE_DETECTED)) == 1


async def test_concurrent_refresh_same_client_both_succeed_within_grace(
    factory: Factory, setup: tuple[User, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    user, client_id = setup
    async with factory() as db:
        service = _service(db)
        _, code = await approved_code(service, user, client_id)
        pair = await service.exchange_code(client_id, code, always_eligible)
        grant = await service.load_refresh(client_id, pair.refresh_token)
        assert grant is not None
    _hold_until_both_arrive(monkeypatch, "mark_rotated")

    results = await asyncio.gather(
        _rotate(factory, client_id, grant),
        _rotate(factory, client_id, grant),
        return_exceptions=True,
    )

    assert all(isinstance(r, TokenPair) for r in results), results
    assert len(await _events(factory, EVENT_REFRESHED)) == 1
    assert len(await _events(factory, EVENT_REFRESH_GRACE)) == 1
    assert await _events(factory, EVENT_REUSE_DETECTED) == []


async def test_concurrent_consent_approve_exactly_one_code(
    factory: Factory, setup: tuple[User, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    user, client_id = setup
    async with factory() as db:
        txn = await begin(_service(db), client_id)
    _hold_until_both_arrive(monkeypatch, "consume_request")

    results = await asyncio.gather(
        _approve(factory, txn, user),
        _approve(factory, txn, user),
        return_exceptions=True,
    )

    urls = [r for r in results if isinstance(r, str)]
    errors = [r for r in results if isinstance(r, BaseException)]
    assert len(urls) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], AuthorizationRequestNotFoundError)
    async with factory() as db:
        codes = (await db.execute(select(OAuthCode))).scalars().all()
    assert len(codes) == 1

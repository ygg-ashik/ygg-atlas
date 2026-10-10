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
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import col, select
from structlog.testing import capture_logs

from app.identity.api_tokens import (
    EVENT_REFRESH_GRACE,
    EVENT_REFRESHED,
    EVENT_REUSE_DETECTED,
    REVOKED_BY_ADMIN,
    REVOKED_CODE_REUSE,
    REVOKED_USER_DISABLED,
    CredentialActor,
)
from app.identity.credentials import TokenService
from app.identity.models import ApiToken, CredentialEvent, OAuthCode, User, UserStatus
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
    issued_pair,
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


def _assert_no_database_error(
    result: object, logs: Sequence[Mapping[str, Any]]
) -> None:
    """A rotation that lost a race must lose cleanly (a TokenPair, or a definite
    refusal), never as a deadlock victim (GrantUnavailableError)."""
    assert isinstance(result, TokenPair | OAuthGrantError), result
    assert not [e for e in logs if e["event"] == "oauth.database_error"], logs


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
    """Hold each caller at `CredentialRepository.<method>` until both arrive, or
    0.5 s pass, so the two callers really do race instead of running one after the
    other. Note: issuing callers take the client row lock first (touch_client), so
    held at mark_code_used or mark_rotated the second caller blocks there and
    reaches the conditional UPDATE only after the winner commits; these tests prove
    the outcome, and the conditional UPDATE is defence in depth."""
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


async def _revoke_family(factory: Factory, grant: RefreshGrant) -> int:
    """What an admin disconnect does from another request (credentials.py)."""
    async with factory() as db:
        repository = CredentialRepository(db)
        count = await repository.revoke_family(
            grant.family_id, REVOKED_BY_ADMIN, datetime.now(UTC)
        )
        await repository.commit()
        return count


async def test_family_revoke_racing_a_rotation_leaves_no_live_token(
    factory: Factory, setup: tuple[User, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The family lock: without it a revoke can land between mark_rotated and the
    new pair's insert and miss the new pair. Both callers are released together at
    lock_family and the rotation is slowed inside its window, so whichever wins,
    the revoke must still cover everything."""
    user, client_id = setup
    async with factory() as db:
        service = _service(db)
        _, code = await approved_code(service, user, client_id)
        pair = await service.exchange_code(client_id, code, always_eligible)
        grant = await service.load_refresh(client_id, pair.refresh_token)
        assert grant is not None
    _hold_until_both_arrive(monkeypatch, "lock_family")
    original = CredentialRepository.mark_rotated

    async def slow_mark(self: CredentialRepository, *args: Any) -> bool:
        rotated = await original(self, *args)
        await asyncio.sleep(0.3)  # widen the window before the insert
        return rotated

    monkeypatch.setattr(CredentialRepository, "mark_rotated", slow_mark)

    with capture_logs() as logs:
        results = await asyncio.gather(
            _rotate(factory, client_id, grant),
            _revoke_family(factory, grant),
            return_exceptions=True,
        )

    _assert_no_database_error(results[0], logs)
    assert isinstance(results[1], int), results
    async with factory() as db:
        live = await CredentialRepository(db).family_has_live_token(
            grant.family_id, datetime.now(UTC)
        )
    assert not live


async def _revoke_client_later(factory: Factory, client_id: str) -> bool:
    """An admin revokes the client while the rotation is inside its window."""
    await asyncio.sleep(0.1)
    async with factory() as db:
        return await _service(db).revoke_client(
            client_id, actor=CredentialActor(user_id=None, via="cli")
        )


async def test_client_revoke_racing_a_rotation_neither_deadlocks_nor_leaks(
    factory: Factory, setup: tuple[User, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lock order is client row first. revoke_client locks the oauth_clients row and
    then the client's token rows; a rotation that locked its token row first and
    then touched the client row would deadlock against it. The rotation is slowed
    right after mark_rotated and the revoke starts inside that window."""
    user, client_id = setup
    async with factory() as db:
        service = _service(db)
        _, code = await approved_code(service, user, client_id)
        pair = await service.exchange_code(client_id, code, always_eligible)
        grant = await service.load_refresh(client_id, pair.refresh_token)
        assert grant is not None
    original = CredentialRepository.mark_rotated

    async def slow_mark(self: CredentialRepository, *args: Any) -> bool:
        rotated = await original(self, *args)
        await asyncio.sleep(0.4)
        return rotated

    monkeypatch.setattr(CredentialRepository, "mark_rotated", slow_mark)

    with capture_logs() as logs:
        results = await asyncio.gather(
            _rotate(factory, client_id, grant),
            _revoke_client_later(factory, client_id),
            return_exceptions=True,
        )

    assert results[1] is True, results
    _assert_no_database_error(results[0], logs)
    async with factory() as db:
        live = await CredentialRepository(db).family_has_live_token(
            grant.family_id, datetime.now(UTC)
        )
    assert not live


async def _disable_user_later(factory: Factory, user: User) -> int:
    """What AccessAdmin.update_user does: commit status=disabled, then (its
    post-commit hook) revoke every token of the user from a fresh session."""
    await asyncio.sleep(0.1)
    async with factory() as db:
        await db.execute(
            update(User)
            .where(col(User.id) == user.id)
            .values(status=UserStatus.DISABLED)
        )
        await db.commit()
    async with factory() as db:
        return await TokenService(db).revoke_all_tokens(
            user.id,
            reason=REVOKED_USER_DISABLED,
            actor=CredentialActor(user_id=None, via="cli"),
        )


async def _revoke_all_later(factory: Factory, user: User) -> int:
    """An admin or CLI revoke-all on an ACTIVE user (incident response): no disable,
    so only the revoke itself can stop a pair being minted beside it."""
    await asyncio.sleep(0.1)
    async with factory() as db:
        return await TokenService(db).revoke_all_tokens(
            user.id,
            reason=REVOKED_BY_ADMIN,
            actor=CredentialActor(user_id=None, via="cli"),
        )


async def _rotation_racing(
    factory: Factory,
    setup: tuple[User, str],
    other: Callable[[Factory, User], Awaitable[int]],
) -> None:
    """Rotates a refresh token with a slowed eligibility check (between the user
    check and the insert of the new pair) while `other` runs; afterwards the user
    must hold no live token and neither side may have failed on the database."""
    user, client_id = setup
    async with factory() as db:
        service = _service(db)
        _, code = await approved_code(service, user, client_id)
        pair = await service.exchange_code(client_id, code, always_eligible)
        grant = await service.load_refresh(client_id, pair.refresh_token)
        assert grant is not None

    async def slow_eligible(_user_id: object) -> bool:
        await asyncio.sleep(0.4)
        return True

    async def rotate() -> TokenPair:
        async with factory() as db:
            return await _service(db).rotate_refresh(client_id, grant, slow_eligible)

    with capture_logs() as logs:
        results = await asyncio.gather(
            rotate(), other(factory, user), return_exceptions=True
        )

    _assert_no_database_error(results[0], logs)
    assert isinstance(results[1], int), results
    async with factory() as db:
        live = (
            await db.execute(
                select(ApiToken).where(
                    col(ApiToken.user_id) == user.id,
                    col(ApiToken.revoked_at).is_(None),
                )
            )
        ).all()
    assert live == []


async def test_user_disable_racing_a_rotation_leaves_no_live_token(
    factory: Factory, setup: tuple[User, str]
) -> None:
    """The user row lock (FOR SHARE on issue): a rotation that read the user as
    active before the disable committed must not insert a pair the revoke-all
    never sees (it would come back to life on re-enable)."""
    await _rotation_racing(factory, setup, _disable_user_later)


async def test_revoke_all_on_an_active_user_racing_a_rotation_leaves_no_live_token(
    factory: Factory, setup: tuple[User, str]
) -> None:
    """Incident response: revoke_user_tokens locks the user row (FOR NO KEY
    UPDATE) before the token rows, so it waits for an issuer holding the row FOR
    SHARE and then sees the new pair; an issuer arriving later waits at lock_user
    and finds its refresh token already revoked."""
    await _rotation_racing(factory, setup, _revoke_all_later)


async def _revoke_access_token_later(factory: Factory, user: User) -> int:
    """An admin revokes the user's live OAuth access token by id
    (DELETE /admin/tokens/{id}): the whole family must go."""
    await asyncio.sleep(0.1)
    async with factory() as db:
        access_id = (
            await db.execute(
                select(col(ApiToken.id)).where(
                    col(ApiToken.user_id) == user.id,
                    col(ApiToken.kind) == "oauth_access",
                    col(ApiToken.revoked_at).is_(None),
                )
            )
        ).scalar_one()
        await TokenService(db).revoke_token(
            access_id,
            reason=REVOKED_BY_ADMIN,
            actor=CredentialActor(user_id=None, via="cli"),
        )
        return 1


async def test_revoking_an_access_token_racing_a_rotation_leaves_no_live_token(
    factory: Factory, setup: tuple[User, str]
) -> None:
    await _rotation_racing(factory, setup, _revoke_access_token_later)


async def test_revoke_all_racing_a_code_exchange_leaves_nothing_live(
    factory: Factory, setup: tuple[User, str]
) -> None:
    """Revoke-all spends unused codes under the user row lock: an exchange either
    commits its pair first (and the revoke covers it) or finds its code gone."""
    user, client_id = setup
    async with factory() as db:
        _, grant = await approved_code(_service(db), user, client_id)

    async def slow_eligible(_user_id: object) -> bool:
        await asyncio.sleep(0.4)
        return True

    async def exchange() -> TokenPair:
        async with factory() as db:
            return await _service(db).exchange_code(client_id, grant, slow_eligible)

    with capture_logs() as logs:
        results = await asyncio.gather(
            exchange(), _revoke_all_later(factory, user), return_exceptions=True
        )

    _assert_no_database_error(results[0], logs)
    assert isinstance(results[1], int), results
    async with factory() as db:
        live = (
            await db.execute(
                select(ApiToken).where(
                    col(ApiToken.user_id) == user.id,
                    col(ApiToken.revoked_at).is_(None),
                )
            )
        ).all()
        unused = (
            await db.execute(select(OAuthCode).where(col(OAuthCode.used_at).is_(None)))
        ).all()
    assert live == []
    assert unused == []


async def test_overlapping_multi_row_revokes_do_not_deadlock(
    factory: Factory, setup: tuple[User, str]
) -> None:
    """An outcome test: a family, a client and a user revoke over the same rows
    all finish and revoke each row once. It cannot force opposing lock orders
    (small-table scans lock in a stable order anyway); the id-ordered locking in
    `_locked_in_id_order` is what rules them out on real tables."""
    user, client_id = setup
    async with factory() as db:
        service = _service(db)
        pairs = [await issued_pair(service, user, client_id) for _ in range(4)]
    family = pairs[0].family_id
    now = datetime.now(UTC)

    async def revoke(how: str) -> int:
        async with factory() as db:
            repository = CredentialRepository(db)
            if how == "family":
                count = await repository.revoke_family(family, REVOKED_BY_ADMIN, now)
            elif how == "client":
                count = await repository.revoke_client_tokens(
                    client_id, REVOKED_BY_ADMIN, now
                )
            else:
                count = await repository.revoke_user_tokens(
                    user.id, REVOKED_BY_ADMIN, now
                )
            await asyncio.sleep(0.05)  # hold the row locks a moment
            await repository.commit()
            return count

    results = await asyncio.gather(
        revoke("user"), revoke("client"), revoke("family"), return_exceptions=True
    )

    counts = [r for r in results if isinstance(r, int)]
    assert len(counts) == 3, results
    assert sum(counts) == 8  # 4 pairs, each row revoked exactly once
    async with factory() as db:
        live = await db.execute(
            select(ApiToken).where(col(ApiToken.revoked_at).is_(None))
        )
        assert live.all() == []

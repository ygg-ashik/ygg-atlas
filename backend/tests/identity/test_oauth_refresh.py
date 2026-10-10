"""Refresh rotation with reuse detection and the 30 s same-client grace (D6)."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select
from structlog.testing import capture_logs

from app.identity.api_tokens import (
    EVENT_FAMILY_REVOKED,
    EVENT_REFRESH_GRACE,
    EVENT_REFRESHED,
    EVENT_REUSE_DETECTED,
    REVOKED_AUDIENCE_CHANGED,
    REVOKED_BY_ADMIN,
    REVOKED_CLIENT,
    REVOKED_CROSS_CLIENT,
    REVOKED_NO_MCP_USE,
    REVOKED_REFRESH_REUSE,
    REVOKED_ROTATED,
    REVOKED_USER_DISABLED,
    CredentialActor,
    TokenKind,
    hash_secret,
    kind_of,
)
from app.identity.credentials import TokenService
from app.identity.models import ApiToken, CredentialEvent, User
from app.identity.oauth import (
    EligibilityUnavailableError,
    GrantUnavailableError,
    OAuthGrantError,
    OAuthService,
    RefreshGrant,
    TokenPair,
)
from app.identity.repository import CredentialRepository
from tests.access_helpers import make_user
from tests.identity.oauth_helpers import (
    Clock,
    always_eligible,
    credential_db,
    issued_pair,
    never_eligible,
    oauth_config,
    register_public_client,
)

GRACE = timedelta(seconds=30)


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """This module's own cheap database (overrides the shared, seeded `db`)."""
    async with credential_db() as session:
        yield session


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def service(db: AsyncSession, clock: Clock) -> OAuthService:
    return OAuthService(db, oauth_config(), clock=clock)


@pytest.fixture
async def user(db: AsyncSession) -> User:
    return await make_user(db, "alice@yougotagift.com")


@pytest.fixture
async def client_id(service: OAuthService) -> str:
    return await register_public_client(service)


@pytest.fixture
async def pair(service: OAuthService, user: User, client_id: str) -> TokenPair:
    return await issued_pair(service, user, client_id)


async def _grant(service: OAuthService, client_id: str, raw: str) -> RefreshGrant:
    grant = await service.load_refresh(client_id, raw)
    assert grant is not None
    return grant


async def _rotate(service: OAuthService, client_id: str, raw: str) -> TokenPair:
    return await service.rotate_refresh(
        client_id, await _grant(service, client_id, raw), always_eligible
    )


async def _row(db: AsyncSession, raw: str) -> ApiToken:
    result = await db.execute(
        select(ApiToken)
        .where(col(ApiToken.token_hash) == hash_secret(raw))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def _family_reasons(db: AsyncSession, pair: TokenPair) -> set[str | None]:
    result = await db.execute(
        select(ApiToken)
        .where(col(ApiToken.family_id) == pair.family_id)
        .execution_options(populate_existing=True)
    )
    return {row.revoked_reason for row in result.scalars().all()}


async def _family_live(db: AsyncSession, pair: TokenPair) -> bool:
    return await CredentialRepository(db).family_has_live_token(
        pair.family_id, Clock().now
    )


async def _events(db: AsyncSession, event: str) -> list[CredentialEvent]:
    result = await db.execute(
        select(CredentialEvent).where(col(CredentialEvent.event) == event)
    )
    return list(result.scalars().all())


async def test_load_refresh_binds_the_row(
    db: AsyncSession, service: OAuthService, client_id: str, pair: TokenPair, user: User
) -> None:
    grant = await _grant(service, client_id, pair.refresh_token)
    row = await _row(db, pair.refresh_token)
    assert grant.token_id == row.id
    assert grant.family_id == pair.family_id
    assert grant.user_id == user.id
    assert grant.client_id == client_id
    assert grant.display == pair.refresh_token[:14]
    assert pair.refresh_token not in repr(grant)


async def test_refresh_rotates_and_revokes_the_old_token(
    db: AsyncSession, service: OAuthService, client_id: str, pair: TokenPair
) -> None:
    new = await _rotate(service, client_id, pair.refresh_token)

    assert new.family_id == pair.family_id
    assert new.user_id == pair.user_id
    assert new.refresh_token != pair.refresh_token
    assert kind_of(new.access_token) is TokenKind.OAUTH_ACCESS
    assert kind_of(new.refresh_token) is TokenKind.OAUTH_REFRESH
    assert (await _row(db, pair.refresh_token)).revoked_reason == REVOKED_ROTATED
    assert (await _row(db, new.refresh_token)).revoked_at is None
    assert (await _row(db, new.access_token)).family_id == pair.family_id
    [event] = await _events(db, EVENT_REFRESHED)
    assert event.details["family_id"] == str(pair.family_id)


async def test_refresh_is_sliding(
    db: AsyncSession,
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    clock: Clock,
) -> None:
    clock.advance(timedelta(days=20))
    new = await _rotate(service, client_id, pair.refresh_token)
    row = await _row(db, new.refresh_token)
    assert row.expires_at.replace(tzinfo=None) == (
        clock.now + timedelta(days=30)
    ).replace(tzinfo=None)


async def test_same_client_retry_within_30s_gets_a_fresh_pair(
    db: AsyncSession,
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    clock: Clock,
) -> None:
    first = await _rotate(service, client_id, pair.refresh_token)
    clock.advance(GRACE - timedelta(seconds=1))
    with capture_logs() as logs:
        second = await _rotate(service, client_id, pair.refresh_token)

    assert second.family_id == pair.family_id
    assert second.refresh_token != first.refresh_token
    assert (await _row(db, first.refresh_token)).revoked_at is None  # sibling lives
    assert (await _row(db, second.refresh_token)).revoked_at is None
    [event] = await _events(db, EVENT_REFRESH_GRACE)
    assert event.details["family_id"] == str(pair.family_id)
    assert any(entry["event"] == "oauth.refresh_grace" for entry in logs)
    assert await _events(db, EVENT_REUSE_DETECTED) == []


async def test_same_client_reuse_after_30s_revokes_the_family(
    db: AsyncSession,
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    clock: Clock,
) -> None:
    await _rotate(service, client_id, pair.refresh_token)
    clock.advance(GRACE + timedelta(seconds=1))
    with pytest.raises(OAuthGrantError) as caught:
        await _rotate(service, client_id, pair.refresh_token)

    assert caught.value.error == "invalid_grant"
    assert not await _family_live(db, pair)
    assert REVOKED_REFRESH_REUSE in await _family_reasons(db, pair)
    [event] = await _events(db, EVENT_REUSE_DETECTED)
    assert event.details == {"family_id": str(pair.family_id), "kind": "refresh"}


async def test_cross_client_reuse_revokes_the_family_without_grace(
    db: AsyncSession,
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    clock: Clock,
) -> None:
    await _rotate(service, client_id, pair.refresh_token)
    other = await register_public_client(service)
    clock.advance(timedelta(seconds=1))

    assert await service.load_refresh(other, pair.refresh_token) is None
    assert not await _family_live(db, pair)
    assert REVOKED_CROSS_CLIENT in await _family_reasons(db, pair)
    [event] = await _events(db, EVENT_REUSE_DETECTED)
    assert event.client_id == client_id  # the family's own client
    assert event.details == {
        "family_id": str(pair.family_id),
        "kind": "refresh",
        "presented_by_client_id": other,  # forensics: who replayed it
    }


async def test_cross_client_presentation_of_a_live_token_revokes_it(
    db: AsyncSession, service: OAuthService, pair: TokenPair
) -> None:
    other = await register_public_client(service)
    assert await service.load_refresh(other, pair.refresh_token) is None
    assert await _family_reasons(db, pair) == {REVOKED_CROSS_CLIENT}


async def test_a_grant_rotated_by_another_client_fails(
    service: OAuthService, client_id: str, pair: TokenPair
) -> None:
    grant = await _grant(service, client_id, pair.refresh_token)
    other = await register_public_client(service)
    with pytest.raises(OAuthGrantError):
        await service.rotate_refresh(other, grant, always_eligible)


async def test_grace_never_revives_a_revoked_family(
    db: AsyncSession,
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    clock: Clock,
) -> None:
    await _rotate(service, client_id, pair.refresh_token)
    await CredentialRepository(db).revoke_family(
        pair.family_id, REVOKED_BY_ADMIN, clock.now
    )
    await db.commit()
    clock.advance(timedelta(seconds=5))
    with pytest.raises(OAuthGrantError):
        await _rotate(service, client_id, pair.refresh_token)
    assert len(await _events(db, EVENT_REUSE_DETECTED)) == 1
    assert not await _family_live(db, pair)
    assert await _events(db, EVENT_REFRESH_GRACE) == []


async def test_a_grace_issue_rechecks_eligibility_and_revokes_on_failure(
    db: AsyncSession,
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    clock: Clock,
) -> None:
    await _rotate(service, client_id, pair.refresh_token)
    clock.advance(timedelta(seconds=5))
    grant = await _grant(service, client_id, pair.refresh_token)
    with pytest.raises(OAuthGrantError):
        await service.rotate_refresh(client_id, grant, never_eligible)
    assert not await _family_live(db, pair)
    assert REVOKED_NO_MCP_USE in await _family_reasons(db, pair)
    assert await _events(db, EVENT_REFRESH_GRACE) == []
    [event] = await _events(db, EVENT_FAMILY_REVOKED)
    assert event.details == {"family_id": str(pair.family_id), "reason": "no_mcp_use"}


async def test_lock_family_is_a_no_op_on_sqlite(db: AsyncSession) -> None:
    await CredentialRepository(db).lock_family(uuid4())  # PG only; never raises here


async def test_lock_user_is_a_no_op_on_sqlite(db: AsyncSession) -> None:
    await CredentialRepository(db).lock_user(uuid4())  # PG only; never raises here


async def _broken_eligibility(_user_id: object) -> bool:
    raise EligibilityUnavailableError


async def test_an_eligibility_check_failure_on_rotation_revokes_nothing(
    db: AsyncSession,
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
) -> None:
    """A transient failure must not read as "no mcp:use": the family survives, the
    presented token is not rotated, nothing is issued, and a retry works."""
    grant = await _grant(service, client_id, pair.refresh_token)
    with capture_logs() as logs, pytest.raises(GrantUnavailableError):
        await service.rotate_refresh(client_id, grant, _broken_eligibility)
    assert await _family_reasons(db, pair) == {None}
    assert await _events(db, EVENT_FAMILY_REVOKED) == []
    assert await _events(db, EVENT_REFRESHED) == []
    [entry] = [e for e in logs if e["event"] == "oauth.eligibility_unavailable"]
    assert entry["family_id"] == str(pair.family_id)
    await _rotate(service, client_id, pair.refresh_token)


async def test_an_eligibility_check_failure_on_a_grace_issue_revokes_nothing(
    db: AsyncSession,
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    clock: Clock,
) -> None:
    await _rotate(service, client_id, pair.refresh_token)
    clock.advance(timedelta(seconds=5))
    grant = await _grant(service, client_id, pair.refresh_token)
    with pytest.raises(GrantUnavailableError):
        await service.rotate_refresh(client_id, grant, _broken_eligibility)
    assert await _family_live(db, pair)
    assert await _events(db, EVENT_FAMILY_REVOKED) == []
    assert await _events(db, EVENT_REFRESH_GRACE) == []


async def test_superseded_token_is_reuse(
    db: AsyncSession,
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    clock: Clock,
) -> None:
    second = await _rotate(service, client_id, pair.refresh_token)
    clock.advance(timedelta(minutes=5))
    await _rotate(service, client_id, second.refresh_token)  # the family lives on
    with pytest.raises(OAuthGrantError):
        await _rotate(service, client_id, pair.refresh_token)
    assert not await _family_live(db, pair)


async def test_an_admin_revoked_token_is_dead_not_reuse(
    db: AsyncSession,
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    clock: Clock,
) -> None:
    """A token revoked for any reason but rotation is simply dead: the legitimate
    client presenting it is no replay, so no alarm and no further revoke."""
    row = await _row(db, pair.refresh_token)
    await CredentialRepository(db).revoke_token(row.id, REVOKED_BY_ADMIN, clock.now)
    await db.commit()
    with capture_logs() as logs, pytest.raises(OAuthGrantError):
        await _rotate(service, client_id, pair.refresh_token)
    assert await _family_reasons(db, pair) == {REVOKED_BY_ADMIN, None}
    assert await _events(db, EVENT_REUSE_DETECTED) == []
    assert await _events(db, EVENT_FAMILY_REVOKED) == []
    assert not [e for e in logs if e["event"] == EVENT_REUSE_DETECTED]


async def test_refresh_after_an_admin_revoke_all_is_no_reuse_alarm(
    db: AsyncSession,
    service: OAuthService,
    user: User,
    client_id: str,
    pair: TokenPair,
) -> None:
    await TokenService(db).revoke_all_tokens(
        user.id, reason=REVOKED_BY_ADMIN, actor=CredentialActor(None, "cli")
    )
    with capture_logs() as logs, pytest.raises(OAuthGrantError) as caught:
        await _rotate(service, client_id, pair.refresh_token)
    assert caught.value.error == "invalid_grant"
    assert await _family_reasons(db, pair) == {REVOKED_BY_ADMIN}
    assert await _events(db, EVENT_REUSE_DETECTED) == []
    assert not [e for e in logs if e["event"] == EVENT_REUSE_DETECTED]


async def test_refresh_rechecks_the_user(
    db: AsyncSession, service: OAuthService, client_id: str, pair: TokenPair, user: User
) -> None:
    grant = await _grant(service, client_id, pair.refresh_token)
    await make_user(db, user.email, status="disabled")
    with pytest.raises(OAuthGrantError):
        await service.rotate_refresh(client_id, grant, always_eligible)
    assert await _family_reasons(db, pair) == {REVOKED_USER_DISABLED}
    [event] = await _events(db, EVENT_FAMILY_REVOKED)
    assert event.details == {
        "family_id": str(pair.family_id),
        "reason": "user_disabled",
    }


async def test_refresh_rechecks_mcp_use(
    db: AsyncSession, service: OAuthService, client_id: str, pair: TokenPair
) -> None:
    grant = await _grant(service, client_id, pair.refresh_token)
    with pytest.raises(OAuthGrantError):
        await service.rotate_refresh(client_id, grant, never_eligible)
    assert await _family_reasons(db, pair) == {REVOKED_NO_MCP_USE}


async def test_refresh_rechecks_the_audience(
    db: AsyncSession, client_id: str, pair: TokenPair, clock: Clock
) -> None:
    moved = OAuthService(
        db,
        oauth_config(resource="https://atlas.example.com/mcp-server/mcp"),
        clock=clock,
    )
    with pytest.raises(OAuthGrantError):
        await _rotate(moved, client_id, pair.refresh_token)
    assert await _family_reasons(db, pair) == {REVOKED_AUDIENCE_CHANGED}


async def test_refresh_for_a_revoked_client_fails(
    db: AsyncSession, service: OAuthService, client_id: str, pair: TokenPair
) -> None:
    grant = await _grant(service, client_id, pair.refresh_token)
    await CredentialRepository(db).revoke_client(client_id, Clock().now)
    await db.commit()
    with pytest.raises(OAuthGrantError):
        await service.rotate_refresh(client_id, grant, always_eligible)
    assert await _family_reasons(db, pair) == {REVOKED_CLIENT}


async def test_refresh_after_revoke_client_fails(
    service: OAuthService, client_id: str, pair: TokenPair
) -> None:
    await service.revoke_client(client_id, actor=CredentialActor(None, "cli"))
    with pytest.raises(OAuthGrantError):
        await _rotate(service, client_id, pair.refresh_token)


async def test_expired_refresh_token_fails(
    db: AsyncSession,
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    clock: Clock,
) -> None:
    clock.advance(timedelta(days=30, seconds=1))
    with pytest.raises(OAuthGrantError) as caught:
        await _rotate(service, client_id, pair.refresh_token)
    assert str(caught.value) == "The refresh token is no longer valid."
    assert (await _row(db, pair.refresh_token)).revoked_at is None
    assert await _events(db, EVENT_REFRESHED) == []


async def test_access_token_is_never_accepted_as_refresh(
    service: OAuthService, client_id: str, pair: TokenPair
) -> None:
    assert await service.load_refresh(client_id, pair.access_token) is None
    assert await service.load_refresh(client_id, "atl_ort_" + "A" * 43) is None
    assert await service.load_refresh(client_id, "garbage") is None


async def test_a_vanished_token_fails(
    db: AsyncSession, service: OAuthService, client_id: str, pair: TokenPair
) -> None:
    grant = await _grant(service, client_id, pair.refresh_token)
    await db.delete(await _row(db, pair.refresh_token))
    await db.commit()
    with pytest.raises(OAuthGrantError):
        await service.rotate_refresh(client_id, grant, always_eligible)


def _deadlock() -> DBAPIError:
    return DBAPIError("UPDATE api_tokens ...", {}, Exception("deadlock detected"))


async def test_a_database_error_during_rotation_is_unavailable(
    db: AsyncSession,
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GrantUnavailableError (the edge: server_error), never a raw DBAPIError and
    never invalid_grant: the refresh token is still good."""
    grant = await _grant(service, client_id, pair.refresh_token)

    async def broken(self: CredentialRepository, *args: object) -> bool:
        raise _deadlock()

    monkeypatch.setattr(CredentialRepository, "mark_rotated", broken)
    with capture_logs() as logs, pytest.raises(GrantUnavailableError) as caught:
        await service.rotate_refresh(client_id, grant, always_eligible)
    assert "deadlock" not in str(caught.value)
    [entry] = [e for e in logs if e["event"] == "oauth.database_error"]
    assert entry["error"] == "DBAPIError"
    assert entry["op"] == "rotate_refresh"
    assert pair.refresh_token not in str(logs)
    # the session is usable afterwards: nothing was rotated
    assert (await _row(db, pair.refresh_token)).revoked_at is None


async def test_a_database_error_while_loading_a_refresh_is_unavailable(
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_refresh is the SDK token handler's entry too: a database error there
    is GrantUnavailableError (server_error), not 'not found' (invalid_grant)."""

    async def broken(self: CredentialRepository, *args: object) -> None:
        raise _deadlock()

    monkeypatch.setattr(CredentialRepository, "token_by_hash", broken)
    with capture_logs() as logs, pytest.raises(GrantUnavailableError):
        await service.load_refresh(client_id, pair.refresh_token)
    [entry] = [e for e in logs if e["event"] == "oauth.database_error"]
    assert entry["error"] == "DBAPIError"
    assert entry["op"] == "load_refresh"
    assert pair.refresh_token not in str(logs)


async def _broken_revoke(self: CredentialRepository, *args: object) -> int:
    raise _deadlock()


async def test_a_failed_cross_client_revoke_is_logged_with_its_family(
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = await register_public_client(service)
    monkeypatch.setattr(CredentialRepository, "revoke_family", _broken_revoke)
    with capture_logs() as logs, pytest.raises(GrantUnavailableError):
        await service.load_refresh(other, pair.refresh_token)
    [failed] = [e for e in logs if e["event"] == "oauth.reuse_revoke_failed"]
    assert failed["family_id"] == str(pair.family_id)
    assert failed["kind"] == "refresh"
    assert pair.refresh_token not in str(logs)


async def test_a_failed_reuse_revoke_on_rotation_is_logged_with_its_family(
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _rotate(service, client_id, pair.refresh_token)
    clock.advance(GRACE + timedelta(seconds=1))
    grant = await _grant(service, client_id, pair.refresh_token)
    monkeypatch.setattr(CredentialRepository, "revoke_family", _broken_revoke)
    with capture_logs() as logs, pytest.raises(GrantUnavailableError):
        await service.rotate_refresh(client_id, grant, always_eligible)
    [failed] = [e for e in logs if e["event"] == "oauth.reuse_revoke_failed"]
    assert failed["family_id"] == str(pair.family_id)
    [entry] = [e for e in logs if e["event"] == "oauth.database_error"]
    assert entry["op"] == "rotate_refresh"
    assert pair.refresh_token not in str(logs)


def _record_calls(
    monkeypatch: pytest.MonkeyPatch, calls: list[str], *methods: str
) -> None:
    for method in methods:
        original = getattr(CredentialRepository, method)

        async def spy(
            self: CredentialRepository,
            *args: object,
            _name: str = method,
            _original: Any = original,
        ) -> object:
            calls.append(_name)
            return await _original(self, *args)

        monkeypatch.setattr(CredentialRepository, method, spy)


async def test_rotation_locks_the_client_row_before_the_family_and_the_token(
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one global lock order (revoke_client locks the client row, then its
    tokens): client row, family lock, token row. Otherwise rotation deadlocks
    against revoke_client."""
    grant = await _grant(service, client_id, pair.refresh_token)
    calls: list[str] = []
    _record_calls(
        monkeypatch, calls, "touch_client", "lock_family", "lock_user", "mark_rotated"
    )
    await service.rotate_refresh(client_id, grant, always_eligible)
    assert calls[:4] == ["touch_client", "lock_family", "lock_user", "mark_rotated"]


async def test_the_grace_window_is_measured_after_the_lock_wait(
    db: AsyncSession,
    service: OAuthService,
    client_id: str,
    pair: TokenPair,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`now` is read after the locks: a retry that arrived inside the 30 s grace but
    waited past it on the family lock is reuse, not a grace issue."""
    await _rotate(service, client_id, pair.refresh_token)
    clock.advance(timedelta(seconds=5))
    grant = await _grant(service, client_id, pair.refresh_token)
    original = CredentialRepository.lock_family

    async def slow_lock(self: CredentialRepository, family_id: Any) -> None:
        await original(self, family_id)
        clock.advance(GRACE)

    monkeypatch.setattr(CredentialRepository, "lock_family", slow_lock)
    with pytest.raises(OAuthGrantError):
        await service.rotate_refresh(client_id, grant, always_eligible)
    assert await _events(db, EVENT_REFRESH_GRACE) == []
    assert REVOKED_REFRESH_REUSE in await _family_reasons(db, pair)
    assert not await _family_live(db, pair)

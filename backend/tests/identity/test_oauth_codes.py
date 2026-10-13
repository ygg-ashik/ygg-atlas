"""OAuthService codes: load and single-use exchange, reuse revoking the family,
the issue checks, RFC 7009 revocation and what never leaks (D5, D30). Refresh
rotation lives in test_oauth_refresh.py."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError, PendingRollbackError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select
from structlog.testing import capture_logs

from app.identity.api_tokens import (
    EVENT_FAMILY_REVOKED,
    EVENT_REUSE_DETECTED,
    EVENT_TOKENS_ISSUED,
    REVOKED_CODE_REUSE,
    REVOKED_OAUTH_REVOKE,
    CredentialActor,
    TokenKind,
    hash_secret,
    kind_of,
)
from app.identity.models import (
    ApiToken,
    CredentialEvent,
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthCode,
    User,
    UserStatus,
)
from app.identity.oauth import (
    EligibilityUnavailableError,
    GrantUnavailableError,
    OAuthGrantError,
    OAuthService,
)
from app.identity.repository import (
    ClientRepository,
    CodeRepository,
    FamilyRepository,
    UserRepository,
)
from tests.access_helpers import make_user
from tests.identity.credential_helpers import (
    LOOPBACK_REDIRECT,
    assert_no_secret,
    insert_token,
)
from tests.identity.oauth_helpers import (
    RESOURCE,
    Clock,
    always_eligible,
    approved_code,
    auth_request,
    begin,
    credential_db,
    issued_pair,
    never_eligible,
    oauth_config,
    query_param,
    register_public_client,
    registration,
)

ADMIN = CredentialActor(user_id=None, via="cli")


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


async def _events(db: AsyncSession, event: str) -> list[CredentialEvent]:
    result = await db.execute(
        select(CredentialEvent).where(col(CredentialEvent.event) == event)
    )
    return list(result.scalars().all())


async def _family(db: AsyncSession, family_id: object) -> list[ApiToken]:
    result = await db.execute(
        select(ApiToken)
        .where(col(ApiToken.family_id) == family_id)
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


async def test_load_code_binds_everything(
    service: OAuthService, user: User, client_id: str
) -> None:
    request = auth_request()
    consent = await service.begin_authorization(client_id, request)
    raw = query_param(
        await service.approve(query_param(consent, "txn"), user.id), "code"
    )
    grant = await service.load_code(client_id, raw)
    assert grant is not None
    assert grant.client_id == client_id
    assert grant.user_id == user.id
    assert grant.redirect_uri == LOOPBACK_REDIRECT
    assert grant.redirect_uri_provided_explicitly is True
    assert grant.code_challenge == request.code_challenge
    assert grant.resource == RESOURCE
    assert raw not in repr(grant)
    assert grant.display == raw[:6]


async def test_exchange_issues_a_pair_in_the_codes_family(
    db: AsyncSession, service: OAuthService, user: User, client_id: str, clock: Clock
) -> None:
    _, grant = await approved_code(service, user, client_id)
    pair = await service.exchange_code(client_id, grant, always_eligible)

    assert pair.family_id == grant.family_id
    assert pair.user_id == user.id
    assert pair.expires_in == 3600
    assert kind_of(pair.access_token) is TokenKind.OAUTH_ACCESS
    assert kind_of(pair.refresh_token) is TokenKind.OAUTH_REFRESH
    assert pair.access_token not in repr(pair)
    assert pair.refresh_token not in repr(pair)

    rows = {row.kind: row for row in await _family(db, grant.family_id)}
    access = rows[TokenKind.OAUTH_ACCESS]
    refresh = rows[TokenKind.OAUTH_REFRESH]
    assert access.token_hash == hash_secret(pair.access_token)
    assert refresh.token_hash == hash_secret(pair.refresh_token)
    for row in (access, refresh):
        assert row.client_id == client_id
        assert row.user_id == user.id
        assert row.audience == RESOURCE
        assert row.revoked_at is None
    assert access.expires_at.replace(tzinfo=None) == (
        clock.now + timedelta(hours=1)
    ).replace(tzinfo=None)
    assert refresh.expires_at.replace(tzinfo=None) == (
        clock.now + timedelta(days=30)
    ).replace(tzinfo=None)
    [event] = await _events(db, EVENT_TOKENS_ISSUED)
    assert event.user_id == user.id
    assert event.token_id == refresh.id
    assert event.details["family_id"] == str(grant.family_id)


async def test_code_is_single_use_and_reuse_revokes_the_family(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    raw, grant = await approved_code(service, user, client_id)
    await service.exchange_code(client_id, grant, always_eligible)

    assert await service.load_code(client_id, raw) is None
    family = await _family(db, grant.family_id)
    assert len(family) == 2
    assert {row.revoked_reason for row in family} == {REVOKED_CODE_REUSE}
    [event] = await _events(db, EVENT_REUSE_DETECTED)
    assert event.details == {"family_id": str(grant.family_id), "kind": "code"}


async def test_exchanging_a_grant_twice_revokes_the_winners_tokens(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    """The losing exchange of a concurrent pair (C8): it held a loaded grant."""
    _, grant = await approved_code(service, user, client_id)
    await service.exchange_code(client_id, grant, always_eligible)
    with pytest.raises(OAuthGrantError) as caught:
        await service.exchange_code(client_id, grant, always_eligible)
    assert caught.value.error == "invalid_grant"
    assert {row.revoked_reason for row in await _family(db, grant.family_id)} == {
        REVOKED_CODE_REUSE
    }
    assert len(await _events(db, EVENT_REUSE_DETECTED)) == 1


async def test_a_used_code_presented_by_another_client_revokes_the_family(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    raw, grant = await approved_code(service, user, client_id)
    await service.exchange_code(client_id, grant, always_eligible)
    other = await register_public_client(service)

    assert await service.load_code(other, raw) is None
    assert {row.revoked_reason for row in await _family(db, grant.family_id)} == {
        REVOKED_CODE_REUSE
    }
    [event] = await _events(db, EVENT_REUSE_DETECTED)
    assert event.client_id == client_id
    assert event.details == {
        "family_id": str(grant.family_id),
        "kind": "code",
        "presented_by_client_id": other,
    }


async def test_exchange_with_another_clients_grant_fails_and_spends_nothing(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    _, grant = await approved_code(service, user, client_id)
    other = await register_public_client(service)
    with pytest.raises(OAuthGrantError):
        await service.exchange_code(other, grant, always_eligible)
    code = await db.get(OAuthCode, grant.code_id, populate_existing=True)
    assert code is not None
    assert code.used_at is None
    assert await _family(db, grant.family_id) == []


async def test_code_from_another_client_is_not_found(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    other = await register_public_client(service)
    raw, _ = await approved_code(service, user, client_id)
    assert await service.load_code(other, raw) is None
    assert await service.load_code(client_id, "no-such-code") is None
    assert await _events(db, EVENT_REUSE_DETECTED) == []


async def test_expired_code_cannot_be_marked_used(
    db: AsyncSession, service: OAuthService, user: User, client_id: str, clock: Clock
) -> None:
    _, grant = await approved_code(service, user, client_id)
    clock.advance(timedelta(seconds=61))
    with pytest.raises(OAuthGrantError):
        await service.exchange_code(client_id, grant, always_eligible)
    assert await _family(db, grant.family_id) == []
    assert await _events(db, EVENT_REUSE_DETECTED) == []


async def test_exchange_refuses_an_ineligible_user(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    _, grant = await approved_code(service, user, client_id)
    with pytest.raises(OAuthGrantError):
        await service.exchange_code(client_id, grant, never_eligible)
    assert await _family(db, grant.family_id) == []
    code = await db.get(OAuthCode, grant.code_id, populate_existing=True)
    assert code is not None
    assert code.used_at is not None  # the code stays used


@pytest.mark.parametrize(
    "failure", [EligibilityUnavailableError(), RuntimeError("policy store down")]
)
async def test_an_eligibility_check_failure_issues_nothing_and_keeps_the_code(
    db: AsyncSession,
    service: OAuthService,
    user: User,
    client_id: str,
    failure: Exception,
) -> None:
    """A check that could not be made is not "not eligible": nothing is issued
    (fail closed), but the code is not spent either, so the client can retry."""

    async def broken(_user_id: object) -> bool:
        raise failure

    _, grant = await approved_code(service, user, client_id)
    with capture_logs() as logs, pytest.raises(GrantUnavailableError):
        await service.exchange_code(client_id, grant, broken)
    assert await _family(db, grant.family_id) == []
    code = await db.get(OAuthCode, grant.code_id, populate_existing=True)
    assert code is not None
    assert code.used_at is None
    assert any(e["event"] == "oauth.eligibility_unavailable" for e in logs)
    pair = await service.exchange_code(client_id, grant, always_eligible)
    assert pair.family_id == grant.family_id


async def test_exchange_refuses_a_disabled_user(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    _, grant = await approved_code(service, user, client_id)
    await make_user(db, user.email, status="disabled")
    with pytest.raises(OAuthGrantError):
        await service.exchange_code(client_id, grant, always_eligible)
    assert await _family(db, grant.family_id) == []


async def test_exchange_rereads_a_user_the_session_already_holds(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    """The status read after lock_user must come from the database, not from a
    User the session loaded before the lock (here: still 'active' in memory)."""
    _, grant = await approved_code(service, user, client_id)
    assert (await db.get(User, user.id)) is user  # held in the identity map
    await db.execute(
        update(User)
        .where(col(User.id) == user.id)
        .values(status=UserStatus.DISABLED)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    assert user.status == UserStatus.ACTIVE  # the in-memory copy is stale
    with pytest.raises(OAuthGrantError):
        await service.exchange_code(client_id, grant, always_eligible)
    assert await _family(db, grant.family_id) == []


async def test_exchange_refuses_a_service_account(
    db: AsyncSession, service: OAuthService, client_id: str
) -> None:
    bot = await make_user(db, "svc-bot@atlas.internal", kind="service")
    _, grant = await approved_code(service, bot, client_id)
    with pytest.raises(OAuthGrantError):
        await service.exchange_code(client_id, grant, always_eligible)


async def test_exchange_refuses_a_code_bound_to_another_audience(
    db: AsyncSession, user: User, client_id: str, service: OAuthService
) -> None:
    _, grant = await approved_code(service, user, client_id)
    moved = OAuthService(
        db, oauth_config(resource="https://atlas.example.com/mcp-server/mcp")
    )
    with pytest.raises(OAuthGrantError):
        await moved.exchange_code(client_id, grant, always_eligible)


async def test_exchange_refuses_a_revoked_client(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    _, grant = await approved_code(service, user, client_id)
    await service.revoke_client(client_id, actor=ADMIN)
    with pytest.raises(OAuthGrantError):
        await service.exchange_code(client_id, grant, always_eligible)
    assert await _family(db, grant.family_id) == []


async def test_revoke_by_token_id_revokes_the_family(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    pair = await issued_pair(service, user, client_id)
    other = await issued_pair(service, user, client_id)
    access = (
        await db.execute(
            select(ApiToken).where(
                col(ApiToken.token_hash) == hash_secret(pair.access_token)
            )
        )
    ).scalar_one()

    await service.revoke_by_token_id(access.id)

    assert {r.revoked_reason for r in await _family(db, pair.family_id)} == {
        REVOKED_OAUTH_REVOKE
    }
    assert {r.revoked_at for r in await _family(db, other.family_id)} == {None}
    [event] = await _events(db, EVENT_FAMILY_REVOKED)
    assert event.details == {"family_id": str(pair.family_id), "reason": "oauth_revoke"}
    assert event.user_id == user.id


async def test_revoke_by_token_id_ignores_unknown_and_non_oauth_tokens(
    db: AsyncSession, service: OAuthService, user: User
) -> None:
    pat, _ = await insert_token(db, user, TokenKind.PAT)
    await service.revoke_by_token_id(uuid4())
    await service.revoke_by_token_id(pat.id)
    refreshed = await db.get(ApiToken, pat.id, populate_existing=True)
    assert refreshed is not None
    assert refreshed.revoked_at is None
    assert await _events(db, EVENT_FAMILY_REVOKED) == []


async def test_no_secret_reaches_events_or_logs(
    db: AsyncSession, service: OAuthService, user: User
) -> None:
    secret = "c" * 64
    with capture_logs() as logs:
        reg = registration(client_secret=secret, auth_method="client_secret_post")
        await service.register_client(reg)
        txn = await begin(service, reg.client_id)
        redirect = await service.approve(txn, user.id)
        code = query_param(redirect, "code")
        grant = await service.load_code(reg.client_id, code)
        assert grant is not None
        pair = await service.exchange_code(reg.client_id, grant, always_eligible)
        refresh = await service.load_refresh(reg.client_id, pair.refresh_token)
        assert refresh is not None
        rotated = await service.rotate_refresh(reg.client_id, refresh, always_eligible)
        assert await service.load_code(reg.client_id, code) is None  # reuse: logged
        with pytest.raises(OAuthGrantError) as caught:
            await service.rotate_refresh(reg.client_id, refresh, never_eligible)

    haystacks: list[object] = [logs, str(caught.value), repr(caught.value)]
    for model in (
        CredentialEvent,
        ApiToken,
        OAuthCode,
        OAuthAuthorizationRequest,
        OAuthClient,
    ):
        rows = (await db.execute(select(model))).scalars().all()
        haystacks.extend(row.model_dump() for row in rows)
    haystacks.extend([repr(grant), repr(refresh), repr(pair), repr(rotated), repr(reg)])
    secrets_seen = [
        secret,
        txn,
        code,
        pair.access_token,
        pair.refresh_token,
        rotated.access_token,
        rotated.refresh_token,
    ]
    for raw in secrets_seen:
        assert_no_secret(raw, *haystacks)
    assert any(entry["event"] == "oauth.reuse_detected" for entry in logs)


async def test_reuse_log_carries_only_the_family_id(
    service: OAuthService, user: User, client_id: str
) -> None:
    raw, grant = await approved_code(service, user, client_id)
    await service.exchange_code(client_id, grant, always_eligible)
    with capture_logs() as logs:
        await service.load_code(client_id, raw)
    [entry] = [e for e in logs if e["event"] == "oauth.reuse_detected"]
    assert set(entry) - {"event", "log_level"} == {"family_id", "kind"}
    assert entry["family_id"] == str(grant.family_id)


async def test_cross_client_reuse_log_names_the_presenting_client(
    service: OAuthService, user: User, client_id: str
) -> None:
    raw, grant = await approved_code(service, user, client_id)
    await service.exchange_code(client_id, grant, always_eligible)
    other = await register_public_client(service)
    with capture_logs() as logs:
        await service.load_code(other, raw)
    [entry] = [e for e in logs if e["event"] == "oauth.reuse_detected"]
    assert entry["presented_by_client_id"] == other
    assert raw not in str(logs)


async def test_grant_error_messages_are_generic(
    service: OAuthService, user: User, client_id: str, clock: Clock
) -> None:
    _, grant = await approved_code(service, user, client_id)
    clock.advance(timedelta(minutes=2))
    with pytest.raises(OAuthGrantError) as caught:
        await service.exchange_code(client_id, grant, always_eligible)
    assert str(caught.value) == "The authorization code is no longer valid."


async def test_a_database_error_during_exchange_is_unavailable(
    service: OAuthService,
    user: User,
    client_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient failure is GrantUnavailableError (the edge: server_error), never
    a raw DBAPIError and never invalid_grant (which makes a client drop a grant
    that is still good)."""
    _, grant = await approved_code(service, user, client_id)

    async def broken(self: CodeRepository, *args: object) -> bool:
        raise DBAPIError("UPDATE oauth_codes ...", {}, Exception("deadlock detected"))

    monkeypatch.setattr(CodeRepository, "mark_code_used", broken)
    with capture_logs() as logs, pytest.raises(GrantUnavailableError) as caught:
        await service.exchange_code(client_id, grant, always_eligible)
    assert "deadlock" not in str(caught.value)
    assert "oauth_codes" not in str(caught.value)
    [entry] = [e for e in logs if e["event"] == "oauth.database_error"]
    assert entry["op"] == "exchange_code"


async def test_a_database_error_while_loading_a_code_is_unavailable(
    service: OAuthService,
    user: User,
    client_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_code is the SDK token handler's entry too: a database error there is
    GrantUnavailableError (server_error), not 'not found' (invalid_grant)."""
    raw, _ = await approved_code(service, user, client_id)

    async def broken(self: CodeRepository, *args: object) -> None:
        raise DBAPIError("SELECT oauth_codes ...", {}, Exception("connection lost"))

    monkeypatch.setattr(CodeRepository, "code_by_hash", broken)
    with capture_logs() as logs, pytest.raises(GrantUnavailableError):
        await service.load_code(client_id, raw)
    [entry] = [e for e in logs if e["event"] == "oauth.database_error"]
    assert entry["error"] == "DBAPIError"
    assert entry["op"] == "load_code"
    assert raw not in str(logs)


@pytest.mark.parametrize(
    "failure",
    [
        SQLAlchemyTimeoutError("QueuePool limit reached"),
        PendingRollbackError("rolled back"),
    ],
)
async def test_any_sqlalchemy_error_is_unavailable(
    service: OAuthService,
    user: User,
    client_id: str,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    """Pool timeouts and pending rollbacks are not DBAPIErrors, but are transient
    all the same: GrantUnavailableError, never a raw error."""
    raw, grant = await approved_code(service, user, client_id)

    async def broken(self: CodeRepository, *args: object) -> object:
        raise failure

    monkeypatch.setattr(CodeRepository, "code_by_hash", broken)
    monkeypatch.setattr(CodeRepository, "mark_code_used", broken)
    with pytest.raises(GrantUnavailableError):
        await service.load_code(client_id, raw)
    with pytest.raises(GrantUnavailableError):
        await service.exchange_code(client_id, grant, always_eligible)


async def test_a_failed_code_reuse_revoke_is_logged_with_its_family(
    service: OAuthService,
    user: User,
    client_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A replayed code whose family revoke fails must not vanish into a generic
    database error: it is the alarm an operator needs (family id, no secrets)."""
    raw, grant = await approved_code(service, user, client_id)
    await service.exchange_code(client_id, grant, always_eligible)

    async def broken(self: FamilyRepository, *args: object) -> int:
        raise DBAPIError("UPDATE api_tokens ...", {}, Exception("deadlock detected"))

    monkeypatch.setattr(FamilyRepository, "revoke_family", broken)
    with capture_logs() as logs, pytest.raises(GrantUnavailableError):
        await service.load_code(client_id, raw)
    [failed] = [e for e in logs if e["event"] == "oauth.reuse_revoke_failed"]
    assert failed["family_id"] == str(grant.family_id)
    assert failed["kind"] == "code"
    [entry] = [e for e in logs if e["event"] == "oauth.database_error"]
    assert entry["op"] == "load_code"
    assert raw not in str(logs)


async def test_exchange_locks_the_client_row_before_the_family_and_the_code(
    service: OAuthService,
    user: User,
    client_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one global lock order: client row, family lock, user row (FOR SHARE, so
    a disable waits for the issue), then code/token rows."""
    _, grant = await approved_code(service, user, client_id)
    calls: list[str] = []
    for repository, method in (
        (ClientRepository, "touch_client"),
        (FamilyRepository, "lock_family"),
        (UserRepository, "lock_user"),
        (CodeRepository, "mark_code_used"),
    ):
        original = getattr(repository, method)

        async def spy(
            self: object,
            *args: object,
            _name: str = method,
            _original: Any = original,
        ) -> object:
            calls.append(_name)
            return await _original(self, *args)

        monkeypatch.setattr(repository, method, spy)
    await service.exchange_code(client_id, grant, always_eligible)
    assert calls[:4] == ["touch_client", "lock_family", "lock_user", "mark_code_used"]

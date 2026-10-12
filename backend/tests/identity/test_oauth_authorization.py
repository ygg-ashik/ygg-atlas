"""OAuthService authorization requests and consent: begin, pending, approve and
deny, each request usable once (D7, D36)."""

from collections.abc import AsyncIterator
from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.identity.api_tokens import (
    EVENT_CONSENT_APPROVED,
    EVENT_CONSENT_DENIED,
    CredentialActor,
    hash_secret,
)
from app.identity.models import (
    CredentialEvent,
    OAuthAuthorizationRequest,
    OAuthCode,
    User,
)
from app.identity.oauth import (
    AuthorizationRequestNotFoundError,
    OAuthRequestError,
    OAuthService,
)
from tests.access_helpers import make_user
from tests.identity.credential_helpers import (
    LOOPBACK_REDIRECT,
    assert_no_secret,
)
from tests.identity.oauth_helpers import (
    HOSTED_REDIRECT,
    RESOURCE,
    Clock,
    auth_request,
    begin,
    credential_db,
    oauth_config,
    query_param,
    register_public_client,
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


async def test_begin_returns_the_consent_url_with_a_txn_and_stores_its_hash(
    db: AsyncSession, service: OAuthService, client_id: str
) -> None:
    consent_url = await service.begin_authorization(client_id, auth_request())
    assert consent_url.startswith("http://localhost:8080/oauth/consent?txn=")
    txn = query_param(consent_url, "txn")

    row = await db.get(OAuthAuthorizationRequest, hash_secret(txn))
    assert row is not None
    assert row.client_id == client_id
    assert_no_secret(txn, row.model_dump())


async def test_missing_resource_is_bound_to_the_mcp_url(
    db: AsyncSession, service: OAuthService, client_id: str
) -> None:
    url = await service.begin_authorization(client_id, auth_request(resource=None))
    row = await db.get(OAuthAuthorizationRequest, hash_secret(query_param(url, "txn")))
    assert row is not None
    assert row.resource == RESOURCE


@pytest.mark.parametrize(
    "foreign",
    [
        "https://evil.example.com/mcp",
        "http://localhost:8080/mcp-server",
        "http://localhost:8080/mcp-server/mcp?x=1",
        "not a url",
    ],
)
async def test_foreign_resource_is_rejected(
    service: OAuthService, client_id: str, foreign: str
) -> None:
    with pytest.raises(OAuthRequestError) as caught:
        await service.begin_authorization(client_id, auth_request(resource=foreign))
    assert caught.value.error == "invalid_request"


async def test_resource_is_compared_canonically(
    db: AsyncSession, service: OAuthService, client_id: str
) -> None:
    url = await service.begin_authorization(
        client_id, auth_request(resource="http://LOCALHOST:8080/mcp-server/mcp/")
    )
    row = await db.get(OAuthAuthorizationRequest, hash_secret(query_param(url, "txn")))
    assert row is not None
    assert row.resource == RESOURCE  # stored as the configured spelling


@pytest.mark.parametrize(
    "challenge",
    ["plain-verifier", "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-c", "!" * 43, ""],
)
async def test_plain_or_malformed_challenge_is_rejected(
    service: OAuthService, client_id: str, challenge: str
) -> None:
    with pytest.raises(OAuthRequestError):
        await service.begin_authorization(client_id, auth_request(challenge=challenge))


async def test_unregistered_redirect_is_rejected(
    service: OAuthService, client_id: str
) -> None:
    with pytest.raises(OAuthRequestError):
        await service.begin_authorization(
            client_id, auth_request("http://localhost:1/other")
        )


async def test_unknown_client_is_rejected(service: OAuthService) -> None:
    with pytest.raises(OAuthRequestError):
        await service.begin_authorization("no-such-client", auth_request())


async def test_long_state_is_rejected(service: OAuthService, client_id: str) -> None:
    with pytest.raises(OAuthRequestError):
        await service.begin_authorization(client_id, auth_request(state="s" * 501))


async def test_pending_request_expires_after_ten_minutes(
    service: OAuthService, client_id: str, clock: Clock
) -> None:
    txn = await begin(service, client_id)
    clock.advance(timedelta(minutes=9, seconds=59))
    assert await service.pending_request(txn) is not None
    clock.advance(timedelta(seconds=2))
    assert await service.pending_request(txn) is None


async def test_pending_request_shows_the_redirect_host_and_loopback_flag(
    db: AsyncSession, service: OAuthService, clock: Clock
) -> None:
    loopback_id = await register_public_client(service)
    pending = await service.pending_request(await begin(service, loopback_id))
    assert pending is not None
    assert pending.client_id == loopback_id
    assert pending.client_name == "Claude Code"
    assert pending.redirect_uri == LOOPBACK_REDIRECT
    assert pending.redirect_host == "localhost"
    assert pending.loopback is True
    assert pending.expires_at == clock.now + timedelta(minutes=10)

    hosted_id = await register_public_client(service, HOSTED_REDIRECT)
    consent = await service.begin_authorization(
        hosted_id, auth_request(HOSTED_REDIRECT)
    )
    hosted = await service.pending_request(query_param(consent, "txn"))
    assert hosted is not None
    assert hosted.redirect_host == "claude.ai"
    assert hosted.loopback is False


async def test_pending_request_for_unknown_txn_or_revoked_client_is_none(
    db: AsyncSession, service: OAuthService, client_id: str
) -> None:
    assert await service.pending_request("no-such-txn") is None
    txn = await begin(service, client_id)
    await service.revoke_client(client_id, actor=ADMIN)
    assert await service.pending_request(txn) is None


async def test_approve_issues_a_code_bound_to_the_approver(
    db: AsyncSession, service: OAuthService, user: User, client_id: str, clock: Clock
) -> None:
    request = auth_request()
    consent = await service.begin_authorization(client_id, request)
    redirect = await service.approve(query_param(consent, "txn"), user.id)

    assert query_param(redirect, "state") == "state-123"
    raw = query_param(redirect, "code")
    row = (
        await db.execute(
            select(OAuthCode).where(col(OAuthCode.code_hash) == hash_secret(raw))
        )
    ).scalar_one()
    assert row.user_id == user.id
    assert row.client_id == client_id
    assert row.redirect_uri == LOOPBACK_REDIRECT
    assert row.code_challenge == request.code_challenge
    assert row.resource == RESOURCE
    assert_no_secret(raw, row.model_dump())

    [event] = await _events(db, EVENT_CONSENT_APPROVED)
    assert event.user_id == user.id
    assert event.client_id == client_id
    assert event.details == {"family_id": str(row.family_id)}


async def test_approve_is_single_use(
    service: OAuthService, user: User, client_id: str
) -> None:
    txn = await begin(service, client_id)
    await service.approve(txn, user.id)
    with pytest.raises(AuthorizationRequestNotFoundError):
        await service.approve(txn, user.id)
    with pytest.raises(AuthorizationRequestNotFoundError):
        await service.deny(txn, user.id)
    assert await service.pending_request(txn) is None


async def test_cannot_approve_someone_elses_txn_after_consumption(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    mallory = await make_user(db, "mallory@yougotagift.com")
    txn = await begin(service, client_id)
    await service.approve(txn, user.id)
    with pytest.raises(AuthorizationRequestNotFoundError):
        await service.approve(txn, mallory.id)
    codes = (await db.execute(select(OAuthCode))).scalars().all()
    assert [code.user_id for code in codes] == [user.id]


async def test_approve_after_expiry_is_not_found(
    service: OAuthService, user: User, client_id: str, clock: Clock
) -> None:
    txn = await begin(service, client_id)
    clock.advance(timedelta(minutes=11))
    with pytest.raises(AuthorizationRequestNotFoundError):
        await service.approve(txn, user.id)


async def test_approve_for_a_revoked_client_issues_nothing(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    txn = await begin(service, client_id)
    await service.revoke_client(client_id, actor=ADMIN)
    with pytest.raises(AuthorizationRequestNotFoundError):
        await service.approve(txn, user.id)
    assert (await db.execute(select(OAuthCode))).scalars().all() == []
    assert await _events(db, EVENT_CONSENT_APPROVED) == []


async def test_deny_redirects_with_access_denied_and_state(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    txn = await begin(service, client_id)
    redirect = await service.deny(txn, user.id)
    assert redirect.startswith(LOOPBACK_REDIRECT + "?")
    assert query_param(redirect, "error") == "access_denied"
    assert query_param(redirect, "state") == "state-123"
    assert "code=" not in redirect
    [event] = await _events(db, EVENT_CONSENT_DENIED)
    assert event.user_id == user.id
    assert event.client_id == client_id
    with pytest.raises(AuthorizationRequestNotFoundError):
        await service.approve(txn, user.id)


async def test_deny_for_a_revoked_client_is_not_found(
    service: OAuthService, user: User, client_id: str
) -> None:
    txn = await begin(service, client_id)
    await service.revoke_client(client_id, actor=ADMIN)
    with pytest.raises(AuthorizationRequestNotFoundError):
        await service.deny(txn, user.id)


async def test_redirect_is_the_registered_uri(
    service: OAuthService, user: User
) -> None:
    registered = "http://127.0.0.1:33418/cb?keep=1"
    client_id = await register_public_client(service, registered)
    consent = await service.begin_authorization(client_id, auth_request(registered))
    redirect = await service.approve(query_param(consent, "txn"), user.id)
    got, want = urlsplit(redirect), urlsplit(registered)
    assert (got.scheme, got.hostname, got.port, got.path) == (
        want.scheme,
        want.hostname,
        want.port,
        want.path,
    )
    assert query_param(redirect, "keep") == "1"

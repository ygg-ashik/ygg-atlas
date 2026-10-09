"""OAuthService: registration, authorization requests, consent, codes, revocation
and GC (D4-D8, D30, D36). Refresh rotation lives in test_oauth_refresh.py."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select
from structlog.testing import capture_logs

from app.config import Settings
from app.identity.api_tokens import (
    EVENT_CLIENT_REGISTERED,
    EVENT_CLIENT_REVOKED,
    EVENT_CONSENT_APPROVED,
    EVENT_CONSENT_DENIED,
    EVENT_FAMILY_REVOKED,
    EVENT_GC,
    EVENT_REUSE_DETECTED,
    EVENT_TOKENS_ISSUED,
    REVOKED_CLIENT,
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
)
from app.identity.oauth import (
    UNNAMED_CLIENT,
    AuthorizationRequestNotFoundError,
    OAuthConfig,
    OAuthGrantError,
    OAuthRegistrationError,
    OAuthRequestError,
    OAuthService,
    RegisteredClient,
)
from app.identity.repository import CredentialRepository
from tests.access_helpers import make_user
from tests.identity.credential_helpers import (
    LOOPBACK_REDIRECT,
    assert_no_secret,
    insert_token,
    make_client,
)
from tests.identity.oauth_helpers import (
    HOSTED_REDIRECT,
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


# ---- config -------------------------------------------------------------------


def test_config_derives_every_url_from_the_public_url() -> None:
    settings = Settings(
        atlas_public_url="https://atlas.example.com",
        oauth_hosted_redirect_uris=f"{HOSTED_REDIRECT}, https://x.example.com/cb",
    )
    config = OAuthConfig.from_settings(settings)
    assert config.issuer == "https://atlas.example.com/mcp-server"
    assert config.resource == "https://atlas.example.com/mcp-server/mcp"
    assert config.consent_url == "https://atlas.example.com/oauth/consent"
    assert config.hosted_redirect_uris == {
        HOSTED_REDIRECT,
        "https://x.example.com/cb",
    }


# ---- registration ---------------------------------------------------------------


async def test_registration_stores_only_the_secret_hash(
    db: AsyncSession, service: OAuthService
) -> None:
    secret = "s" * 64
    reg = registration(client_secret=secret, auth_method="client_secret_post")
    await service.register_client(reg)

    row = await db.get(OAuthClient, reg.client_id)
    assert row is not None
    assert row.client_secret_hash == hash_secret(secret)
    assert_no_secret(secret, row.model_dump())
    assert secret not in repr(reg)
    client = await service.get_client(reg.client_id)
    assert client is not None
    assert secret not in repr(client)
    assert client.secret_matches(secret)
    assert not client.secret_matches("t" * 64)
    assert not client.secret_matches(None)


async def test_public_client_needs_no_secret(service: OAuthService) -> None:
    client_id = await register_public_client(service)
    client = await service.get_client(client_id)
    assert client is not None
    assert client.secret_hash is None
    assert client.secret_matches(None)
    assert client.secret_matches("ignored")  # public: the auth method decides


def test_a_confidential_client_without_a_stored_hash_never_matches() -> None:
    client = RegisteredClient(
        client_id="c",
        client_name=None,
        redirect_uris=(LOOPBACK_REDIRECT,),
        token_endpoint_auth_method="client_secret_basic",
        grant_types=(),
        response_types=(),
        registered_at=Clock().now,
    )
    assert not client.secret_matches("anything")
    assert not client.secret_matches(None)


async def test_registration_rejects_a_disallowed_redirect(
    service: OAuthService,
) -> None:
    with pytest.raises(OAuthRegistrationError) as caught:
        await service.register_client(
            registration(redirect_uris=(LOOPBACK_REDIRECT, "https://evil.com/cb"))
        )
    assert caught.value.error == "invalid_redirect_uri"


async def test_registration_rejects_no_redirects(service: OAuthService) -> None:
    with pytest.raises(OAuthRegistrationError) as caught:
        await service.register_client(registration(redirect_uris=()))
    assert caught.value.error == "invalid_redirect_uri"


async def test_registration_rejects_too_many_redirects(service: OAuthService) -> None:
    redirects = tuple(f"http://localhost:{port}/cb" for port in range(9000, 9006))
    with pytest.raises(OAuthRegistrationError) as caught:
        await service.register_client(registration(redirect_uris=redirects))
    assert caught.value.error == "invalid_client_metadata"


async def test_registration_rejects_private_key_jwt(service: OAuthService) -> None:
    with pytest.raises(OAuthRegistrationError) as caught:
        await service.register_client(registration(auth_method="private_key_jwt"))
    assert caught.value.error == "invalid_client_metadata"


async def test_registration_rejects_extra_grant_types(service: OAuthService) -> None:
    with pytest.raises(OAuthRegistrationError) as caught:
        await service.register_client(
            registration(
                grant_types=(
                    "authorization_code",
                    "refresh_token",
                    "client_credentials",
                )
            )
        )
    assert caught.value.error == "invalid_client_metadata"


async def test_registration_rejects_other_response_types(
    service: OAuthService,
) -> None:
    with pytest.raises(OAuthRegistrationError):
        await service.register_client(registration(response_types=("code", "token")))


async def test_registration_rejects_a_long_name(service: OAuthService) -> None:
    with pytest.raises(OAuthRegistrationError) as caught:
        await service.register_client(registration(name="x" * 101))
    assert caught.value.error == "invalid_client_metadata"


async def test_registration_rejects_a_secret_that_does_not_fit_the_method(
    service: OAuthService,
) -> None:
    with pytest.raises(OAuthRegistrationError):
        await service.register_client(registration(client_secret="s" * 64))
    with pytest.raises(OAuthRegistrationError):
        await service.register_client(registration(auth_method="client_secret_basic"))


async def test_registration_writes_an_event(
    db: AsyncSession, service: OAuthService
) -> None:
    reg = registration(redirect_uris=(LOOPBACK_REDIRECT, HOSTED_REDIRECT))
    await service.register_client(reg)

    [event] = await _events(db, EVENT_CLIENT_REGISTERED)
    assert event.client_id == reg.client_id
    assert event.via == "oauth"
    assert event.user_id is None
    assert event.details == {
        "name": "Claude Code",
        "redirect_hosts": ["localhost", "claude.ai"],
        "auth_method": "none",
    }


async def test_a_client_without_a_name_is_shown_as_unnamed(
    db: AsyncSession, service: OAuthService, clock: Clock
) -> None:
    reg = registration(name="   ")
    await service.register_client(reg)
    row = await db.get(OAuthClient, reg.client_id)
    assert row is not None
    assert row.client_name is None

    pending = await service.pending_request(await begin(service, reg.client_id))
    assert pending is not None
    assert pending.client_name == UNNAMED_CLIENT == "Unnamed client"
    [summary] = [
        c for c in await service.list_clients() if c.client_id == reg.client_id
    ]
    assert summary.client_name == UNNAMED_CLIENT


async def test_get_client_hides_unknown_and_revoked_clients(
    db: AsyncSession, service: OAuthService
) -> None:
    revoked = await make_client(db, revoked=True)
    assert await service.get_client(revoked.client_id) is None
    assert await service.get_client("no-such-client") is None


async def test_get_client_drops_redirects_the_allowlist_no_longer_allows(
    db: AsyncSession,
) -> None:
    stored = await make_client(db, redirect_uris=(LOOPBACK_REDIRECT, HOSTED_REDIRECT))
    narrowed = OAuthService(db, oauth_config(hosted_redirect_uris=frozenset()))
    client = await narrowed.get_client(stored.client_id)
    assert client is not None
    assert client.redirect_uris == (LOOPBACK_REDIRECT,)

    hosted_only = await make_client(db, redirect_uris=(HOSTED_REDIRECT,))
    assert await narrowed.get_client(hosted_only.client_id) is None


# ---- authorization requests ------------------------------------------------------


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


# ---- consent ---------------------------------------------------------------------


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


# ---- codes -------------------------------------------------------------------------


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


async def test_registration_stores_redirects_in_canonical_form(
    db: AsyncSession, service: OAuthService
) -> None:
    reg = registration(
        redirect_uris=("http://LOCALHOST:7777/x", "http://127.0.0.1:33418")
    )
    await service.register_client(reg)
    row = await db.get(OAuthClient, reg.client_id)
    assert row is not None
    assert row.redirect_uris == ["http://localhost:7777/x", "http://127.0.0.1:33418/"]


async def test_redirects_are_matched_in_canonical_form(
    service: OAuthService, user: User
) -> None:
    """The SDK compares str(AnyUrl) on both sides, so the slash-less spelling a
    client registered must match the slashed one it later sends, and vice versa."""
    client_id = await register_public_client(service, "http://127.0.0.1:33418")
    for spelling in ("http://127.0.0.1:33418/", "http://127.0.0.1:33418"):
        consent = await service.begin_authorization(client_id, auth_request(spelling))
        pending = await service.pending_request(query_param(consent, "txn"))
        assert pending is not None
        assert pending.redirect_uri == "http://127.0.0.1:33418/"
        redirect = await service.approve(query_param(consent, "txn"), user.id)
        assert redirect.startswith("http://127.0.0.1:33418/?code=")


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


async def test_exchange_treats_an_eligibility_error_as_ineligible(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    async def broken(_user_id: object) -> bool:
        raise RuntimeError("policy store down")

    _, grant = await approved_code(service, user, client_id)
    with pytest.raises(OAuthGrantError):
        await service.exchange_code(client_id, grant, broken)
    assert await _family(db, grant.family_id) == []


async def test_exchange_refuses_a_disabled_user(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    _, grant = await approved_code(service, user, client_id)
    await make_user(db, user.email, status="disabled")
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


# ---- revocation and GC ---------------------------------------------------------------


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


async def test_revoke_client_cascades_to_its_tokens(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    pair = await issued_pair(service, user, client_id)
    other_client = await register_public_client(service)
    other = await issued_pair(service, user, other_client)
    actor = CredentialActor(user_id=user.id, via="api")

    assert await service.revoke_client(client_id, actor=actor) is True
    assert await service.revoke_client(client_id, actor=actor) is False
    assert await service.revoke_client("no-such-client", actor=actor) is False

    assert await service.get_client(client_id) is None
    assert {r.revoked_reason for r in await _family(db, pair.family_id)} == {
        REVOKED_CLIENT
    }
    assert {r.revoked_at for r in await _family(db, other.family_id)} == {None}
    [event] = await _events(db, EVENT_CLIENT_REVOKED)
    assert event.client_id == client_id
    assert event.actor_user_id == user.id
    assert event.via == "api"
    assert event.details == {"tokens": 2}


async def test_list_clients_counts_live_families(
    db: AsyncSession, service: OAuthService, user: User, client_id: str, clock: Clock
) -> None:
    await issued_pair(service, user, client_id)
    await issued_pair(service, user, client_id)
    idle = await register_public_client(service)

    summaries = {s.client_id: s for s in await service.list_clients()}
    assert summaries[client_id].active_families == 2
    assert summaries[client_id].client_name == "Claude Code"
    assert summaries[client_id].redirect_uris == (LOOPBACK_REDIRECT,)
    assert summaries[client_id].token_endpoint_auth_method == "none"
    assert summaries[client_id].revoked_at is None
    assert summaries[idle].active_families == 0

    clock.advance(timedelta(days=31))  # every refresh token has expired by then
    summaries = {s.client_id: s for s in await service.list_clients()}
    assert summaries[client_id].active_families == 0


async def test_gc_removes_idle_clients_and_dead_rows_only(
    db: AsyncSession, service: OAuthService, user: User, client_id: str, clock: Clock
) -> None:
    pair = await issued_pair(service, user, client_id)
    pat, _ = await insert_token(db, user, TokenKind.PAT, expires_in=timedelta(days=1))
    idle = await register_public_client(service)

    clock.advance(timedelta(days=91))
    report = await service.gc()

    assert report.codes == 1
    assert report.requests == 1
    assert report.tokens == 2  # the expired pair; the PAT is never collected
    assert report.clients == 2  # the idle client and, now unreferenced, the used one
    assert await db.get(OAuthClient, idle) is None
    assert await db.get(ApiToken, pat.id) is not None
    assert await _family(db, pair.family_id) == []
    [event] = await _events(db, EVENT_GC)
    assert event.via == "system"
    assert event.details == {"codes": 1, "requests": 1, "tokens": 2, "clients": 2}


async def test_gc_keeps_live_rows(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    pair = await issued_pair(service, user, client_id)
    report = await service.gc()
    assert (report.codes, report.requests, report.tokens, report.clients) == (
        0,
        0,
        0,
        0,
    )
    assert len(await _family(db, pair.family_id)) == 2
    assert await service.get_client(client_id) is not None


# ---- leaks ---------------------------------------------------------------------------


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


async def test_grant_error_messages_are_generic(
    service: OAuthService, user: User, client_id: str, clock: Clock
) -> None:
    _, grant = await approved_code(service, user, client_id)
    clock.advance(timedelta(minutes=2))
    with pytest.raises(OAuthGrantError) as caught:
        await service.exchange_code(client_id, grant, always_eligible)
    assert str(caught.value) == "The authorization code is no longer valid."


async def test_a_database_error_during_exchange_is_a_generic_grant_error(
    service: OAuthService,
    user: User,
    client_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SDK token handler must never see a raw DBAPIError (a 500 with a stack)."""
    _, grant = await approved_code(service, user, client_id)

    async def broken(self: CredentialRepository, *args: object) -> bool:
        raise DBAPIError("UPDATE oauth_codes ...", {}, Exception("deadlock detected"))

    monkeypatch.setattr(CredentialRepository, "mark_code_used", broken)
    with pytest.raises(OAuthGrantError) as caught:
        await service.exchange_code(client_id, grant, always_eligible)
    assert caught.value.error == "invalid_grant"
    assert "deadlock" not in str(caught.value)


async def test_a_database_error_while_loading_a_code_is_not_found(
    service: OAuthService,
    user: User,
    client_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_code is the SDK token handler's entry too: a raw DBAPIError there would
    be a 500. It fails closed as 'not found' (invalid_grant)."""
    raw, _ = await approved_code(service, user, client_id)

    async def broken(self: CredentialRepository, *args: object) -> None:
        raise DBAPIError("SELECT oauth_codes ...", {}, Exception("connection lost"))

    monkeypatch.setattr(CredentialRepository, "code_by_hash", broken)
    with capture_logs() as logs:
        assert await service.load_code(client_id, raw) is None
    [entry] = [e for e in logs if e["event"] == "oauth.database_error"]
    assert entry["error"] == "DBAPIError"
    assert raw not in str(logs)


async def test_exchange_locks_the_client_row_before_the_family_and_the_code(
    service: OAuthService,
    user: User,
    client_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one global lock order: client row, family lock, then code/token rows."""
    _, grant = await approved_code(service, user, client_id)
    calls: list[str] = []
    for method in ("touch_client", "lock_family", "mark_code_used"):
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
    await service.exchange_code(client_id, grant, always_eligible)
    assert calls[:3] == ["touch_client", "lock_family", "mark_code_used"]

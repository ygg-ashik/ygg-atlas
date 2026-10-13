"""OAuthService clients: config, dynamic registration, canonical redirects,
client revocation, the admin listing and GC (D4, D8)."""

from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.config import Settings
from app.identity.api_tokens import (
    EVENT_CLIENT_REGISTERED,
    EVENT_CLIENT_REVOKED,
    EVENT_GC,
    REVOKED_CLIENT,
    UNNAMED_CLIENT,
    CredentialActor,
    TokenKind,
    hash_secret,
)
from app.identity.models import (
    ApiToken,
    CredentialEvent,
    OAuthClient,
    OAuthCode,
    User,
)
from app.identity.oauth import (
    OAuthConfig,
    OAuthRegistrationError,
    OAuthService,
    RegisteredClient,
)
from tests.access_helpers import make_user
from tests.identity.credential_helpers import (
    LOOPBACK_REDIRECT,
    assert_no_secret,
    insert_token,
    make_client,
)
from tests.identity.oauth_helpers import (
    HOSTED_REDIRECT,
    Clock,
    approved_code,
    auth_request,
    begin,
    credential_db,
    issued_pair,
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


async def test_revoking_a_client_spends_its_outstanding_codes(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    raw, grant = await approved_code(service, user, client_id)

    assert await service.revoke_client(client_id, actor=ADMIN)

    assert await db.get(OAuthCode, grant.code_id, populate_existing=True) is None
    assert await service.load_code(client_id, raw) is None
    [event] = await _events(db, EVENT_CLIENT_REVOKED)
    assert event.details == {"tokens": 0, "codes": 1}


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
    assert event.details == {"tokens": 2, "codes": 0}


async def test_revoke_client_leaves_expired_tokens_alone(
    db: AsyncSession, service: OAuthService, user: User, client_id: str
) -> None:
    """Only live rows are revoked: an expired row needs no revoke, and leaving it
    out keeps this lock set disjoint from GC's (no deadlock)."""
    pair = await issued_pair(service, user, client_id)
    expired, _ = await insert_token(
        db,
        user,
        TokenKind.OAUTH_REFRESH,
        expires_in=-timedelta(days=40),
        family_id=uuid4(),
        client_id=client_id,
    )

    assert await service.revoke_client(client_id, actor=ADMIN) is True

    untouched = await db.get(ApiToken, expired.id, populate_existing=True)
    assert untouched is not None
    assert untouched.revoked_at is None
    assert untouched.revoked_reason is None
    assert {r.revoked_reason for r in await _family(db, pair.family_id)} == {
        REVOKED_CLIENT
    }
    [event] = await _events(db, EVENT_CLIENT_REVOKED)
    assert event.details == {"tokens": 2, "codes": 0}


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

"""AtlasOAuthProvider and HashedClientAuthenticator, called the way the SDK does."""

import base64
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest
from mcp.server.auth.middleware.client_auth import AuthenticationError
from mcp.server.auth.provider import (
    AuthorizationParams,
    AuthorizeError,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select
from structlog.testing import capture_logs

from app.identity import ApiToken, OAuthClient, User
from app.identity.api_tokens import hash_secret
from app.mcp.oauth_provider import (
    AtlasAuthorizationCode,
    AtlasOAuthProvider,
    HashedClientAuthenticator,
)
from tests.access_helpers import make_user
from tests.identity.credential_helpers import (
    LOOPBACK_REDIRECT,
    assert_no_secret,
    make_client,
)
from tests.identity.oauth_helpers import pkce_pair, query_param
from tests.mcp.oauth_client import (
    CONSENT,
    RESOURCE,
    Store,
    approve_directly,
    form_request,
    oauth_store,
    oauth_test_app,
)

SECRET = "s3cret-" + "x" * 40


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[Store]:
    async with oauth_store(tmp_path) as opened:
        yield opened


@pytest.fixture
def db(store: Store) -> AsyncSession:
    """This module's own database (no demo seed), shared with the provider."""
    return store.db


def _provider(store: Store) -> AtlasOAuthProvider:
    return oauth_test_app(store).provider


async def _user(db: AsyncSession, role: str = "analyst") -> User:
    return await make_user(db, f"u-{uuid4().hex[:8]}@yougotagift.com", role=role)


def _info(
    *,
    redirect: str = LOOPBACK_REDIRECT,
    method: str = "none",
    secret: str | None = None,
) -> OAuthClientInformationFull:
    return OAuthClientInformationFull.model_validate(
        {
            "client_id": f"client-{uuid4()}",
            "client_secret": secret,
            "client_name": "Claude Code",
            "redirect_uris": [redirect],
            "token_endpoint_auth_method": method,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        }
    )


def _params(
    challenge: str, *, resource: str | None = RESOURCE, state: str = "st"
) -> AuthorizationParams:
    return AuthorizationParams(
        state=state,
        scopes=None,
        code_challenge=challenge,
        redirect_uri=AnyUrl(LOOPBACK_REDIRECT),
        redirect_uri_provided_explicitly=True,
        resource=resource,
    )


async def _registered(
    provider: AtlasOAuthProvider, *, method: str = "none", secret: str | None = None
) -> OAuthClientInformationFull:
    info = _info(method=method, secret=secret)
    await provider.register_client(info)
    client = await provider.get_client(info.client_id or "")
    assert client is not None
    return client


async def _code(
    store: Store,
    provider: AtlasOAuthProvider,
    client: OAuthClientInformationFull,
    user: User,
) -> tuple[str, AtlasAuthorizationCode]:
    consent = await provider.authorize(client, _params(pkce_pair()[1]))
    raw, _ = await approve_directly(store, query_param(consent, "txn"), user)
    code = await provider.load_authorization_code(client, raw)
    assert code is not None
    return raw, code


# ---- provider -------------------------------------------------------------------


async def test_get_client_never_returns_a_secret(
    store: Store, db: AsyncSession
) -> None:
    provider = _provider(store)

    client = await _registered(provider, method="client_secret_post", secret=SECRET)

    assert client.client_secret is None
    assert str(client.redirect_uris and client.redirect_uris[0]) == LOOPBACK_REDIRECT
    assert_no_secret(SECRET, client.model_dump_json())


async def test_only_the_secret_hash_is_stored(store: Store, db: AsyncSession) -> None:
    provider = _provider(store)
    client = await _registered(provider, method="client_secret_post", secret=SECRET)

    row = (
        await db.execute(
            select(OAuthClient).where(col(OAuthClient.client_id) == client.client_id)
        )
    ).scalar_one()

    assert row.client_secret_hash == hash_secret(SECRET)
    assert_no_secret(SECRET, row.model_dump())


async def test_register_maps_allowlist_failures_to_invalid_redirect_uri(
    store: Store, db: AsyncSession
) -> None:
    with pytest.raises(RegistrationError) as caught:
        await _provider(store).register_client(
            _info(redirect="https://evil.example/cb")
        )

    assert caught.value.error == "invalid_redirect_uri"


async def test_authorize_returns_the_consent_url(
    store: Store, db: AsyncSession
) -> None:
    provider = _provider(store)
    client = await _registered(provider)

    consent = await provider.authorize(client, _params(pkce_pair()[1]))

    assert consent.startswith(f"{CONSENT}?txn=")


async def test_authorize_maps_a_foreign_resource_to_invalid_request(
    store: Store, db: AsyncSession
) -> None:
    provider = _provider(store)
    client = await _registered(provider)

    with pytest.raises(AuthorizeError) as caught:
        await provider.authorize(
            client, _params(pkce_pair()[1], resource="https://evil.example/mcp")
        )

    assert caught.value.error == "invalid_request"


async def test_authorize_internal_failure_is_a_generic_server_error(
    store: Store, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(store)
    client = await _registered(provider)

    async def broken(*_args: object) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "app.mcp.oauth_provider.OAuthService.begin_authorization", broken
    )
    with capture_logs() as logs, pytest.raises(AuthorizeError) as caught:
        await provider.authorize(client, _params(pkce_pair()[1]))

    assert caught.value.error == "server_error"
    assert "boom" not in (caught.value.error_description or "")
    assert logs[-1]["event"] == "mcp.oauth_authorize_failed"


async def test_code_carrier_holds_only_the_display_prefix(
    store: Store, db: AsyncSession
) -> None:
    provider = _provider(store)
    client = await _registered(provider)

    raw, code = await _code(store, provider, client, await _user(db))

    assert code.code == raw[:6]
    assert code.client_id == client.client_id
    assert str(code.redirect_uri) == LOOPBACK_REDIRECT
    assert code.resource == RESOURCE
    assert_no_secret(raw, repr(code), str(code), code.model_dump_json())


async def test_exchange_and_refresh_carriers_hold_no_secret(
    store: Store, db: AsyncSession
) -> None:
    provider = _provider(store)
    client = await _registered(provider)
    _, code = await _code(store, provider, client, await _user(db))

    pair = await provider.exchange_authorization_code(client, code)
    assert pair.refresh_token is not None
    refresh = await provider.load_refresh_token(client, pair.refresh_token)

    assert pair.token_type == "Bearer"
    assert pair.expires_in == 3600
    assert refresh is not None
    assert refresh.token == pair.refresh_token[:14]
    assert_no_secret(pair.refresh_token, repr(refresh), refresh.model_dump_json())


async def test_exchange_requires_mcp_use(store: Store, db: AsyncSession) -> None:
    provider = _provider(store)
    client = await _registered(provider)
    _, code = await _code(store, provider, client, await _user(db, role="viewer"))

    with pytest.raises(TokenError) as caught:
        await provider.exchange_authorization_code(client, code)

    assert caught.value.error == "invalid_grant"


async def test_refresh_requires_mcp_use(store: Store, db: AsyncSession) -> None:
    provider = _provider(store)
    client = await _registered(provider)
    user = await _user(db)
    _, code = await _code(store, provider, client, user)
    pair = await provider.exchange_authorization_code(client, code)
    assert pair.refresh_token is not None
    await make_user(db, user.email, role="viewer")  # loses mcp:use
    refresh = await provider.load_refresh_token(client, pair.refresh_token)
    assert refresh is not None

    with pytest.raises(TokenError) as caught:
        await provider.exchange_refresh_token(client, refresh, [])

    assert caught.value.error == "invalid_grant"


async def test_dead_refresh_token_is_invalid_grant(
    store: Store, db: AsyncSession
) -> None:
    provider = _provider(store)
    client = await _registered(provider)
    _, code = await _code(store, provider, client, await _user(db))
    pair = await provider.exchange_authorization_code(client, code)
    assert pair.refresh_token is not None
    refresh = await provider.load_refresh_token(client, pair.refresh_token)
    assert refresh is not None
    await provider.revoke_token(refresh)

    with pytest.raises(TokenError) as caught:
        await provider.exchange_refresh_token(client, refresh, [])

    assert caught.value.error == "invalid_grant"


async def test_eligibility_fails_closed(
    store: Store, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _user(db)

    async def broken(*_args: object) -> None:
        raise RuntimeError("policy store down")

    monkeypatch.setattr("app.mcp.oauth_provider.policy_for", broken)
    with capture_logs() as logs:
        assert await _provider(store).eligible(user.id) is False

    assert logs[-1] == {
        "event": "mcp.eligibility_check_failed",
        "error": "RuntimeError",
        "log_level": "error",
    }


async def test_eligibility_needs_an_active_user_with_mcp_use(
    store: Store, db: AsyncSession
) -> None:
    provider = _provider(store)

    assert await provider.eligible((await _user(db)).id) is True
    assert await provider.eligible((await _user(db, role="viewer")).id) is False
    assert await provider.eligible(uuid4()) is False


async def test_revoke_token_revokes_the_family(store: Store, db: AsyncSession) -> None:
    provider = _provider(store)
    client = await _registered(provider)
    _, code = await _code(store, provider, client, await _user(db))
    pair = await provider.exchange_authorization_code(client, code)
    access = await provider.load_access_token(pair.access_token)
    assert access is not None

    await provider.revoke_token(access)

    rows = (
        (
            await db.execute(
                select(ApiToken).where(col(ApiToken.client_id) == client.client_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(row.revoked_at is not None for row in rows)
    assert await provider.load_access_token(pair.access_token) is None


# ---- client authentication --------------------------------------------------------


def _basic(client_id: str, secret: str) -> dict[str, str]:
    pair = f"{quote(client_id, safe='')}:{quote(secret, safe='')}"
    return {"Authorization": f"Basic {base64.b64encode(pair.encode()).decode()}"}


async def _confidential(
    db: AsyncSession, method: str = "client_secret_post"
) -> OAuthClient:
    client = await make_client(db, secret_hash=hash_secret(SECRET))
    client.token_endpoint_auth_method = method
    db.add(client)
    await db.commit()
    return client


def _authenticator(store: Store) -> HashedClientAuthenticator:
    return HashedClientAuthenticator(_provider(store))


async def test_public_client_needs_no_secret(store: Store, db: AsyncSession) -> None:
    client = await make_client(db)

    info = await _authenticator(store).authenticate_request(
        form_request({"client_id": client.client_id})
    )

    assert info.client_id == client.client_id
    assert info.client_secret is None


async def test_confidential_post_secret_ok(store: Store, db: AsyncSession) -> None:
    client = await _confidential(db)

    info = await _authenticator(store).authenticate_request(
        form_request({"client_id": client.client_id, "client_secret": SECRET})
    )

    assert info.client_id == client.client_id
    assert info.client_secret is None


async def test_confidential_basic_secret_ok(store: Store, db: AsyncSession) -> None:
    client = await _confidential(db, "client_secret_basic")

    info = await _authenticator(store).authenticate_request(
        form_request({"client_id": client.client_id}, _basic(client.client_id, SECRET))
    )

    assert info.client_id == client.client_id


@pytest.mark.parametrize("method", ["client_secret_post", "client_secret_basic"])
async def test_wrong_secret_is_rejected(
    store: Store, db: AsyncSession, method: str
) -> None:
    client = await _confidential(db, method)
    wrong = SECRET + "-wrong"
    fields = {"client_id": client.client_id}
    headers = _basic(client.client_id, wrong)
    if method == "client_secret_post":
        fields["client_secret"] = wrong
        headers = {}

    with pytest.raises(AuthenticationError) as caught:
        await _authenticator(store).authenticate_request(form_request(fields, headers))

    assert caught.value.message == "Invalid client credentials"
    assert SECRET not in caught.value.message


@pytest.mark.parametrize("method", ["client_secret_post", "client_secret_basic"])
async def test_missing_secret_is_rejected(
    store: Store, db: AsyncSession, method: str
) -> None:
    client = await _confidential(db, method)

    with pytest.raises(AuthenticationError):
        await _authenticator(store).authenticate_request(
            form_request({"client_id": client.client_id})
        )


async def test_basic_secret_in_the_form_is_not_accepted(
    store: Store, db: AsyncSession
) -> None:
    client = await _confidential(db, "client_secret_basic")

    with pytest.raises(AuthenticationError):
        await _authenticator(store).authenticate_request(
            form_request({"client_id": client.client_id, "client_secret": SECRET})
        )


async def test_basic_client_id_mismatch_is_rejected(
    store: Store, db: AsyncSession
) -> None:
    client = await _confidential(db, "client_secret_basic")

    with pytest.raises(AuthenticationError):
        await _authenticator(store).authenticate_request(
            form_request(
                {"client_id": client.client_id}, _basic("someone-else", SECRET)
            )
        )


@pytest.mark.parametrize(
    "header",
    ["Basic", "Basic !!!not-base64!!!", "Basic bm8tY29sb24=", "Bearer abc"],
    ids=["empty", "not-base64", "no-colon", "wrong-scheme"],
)
async def test_malformed_basic_header_is_rejected(
    store: Store, db: AsyncSession, header: str
) -> None:
    client = await _confidential(db, "client_secret_basic")

    with pytest.raises(AuthenticationError) as caught:
        await _authenticator(store).authenticate_request(
            form_request({"client_id": client.client_id}, {"Authorization": header})
        )

    assert caught.value.message == "Invalid client credentials"


@pytest.mark.parametrize("revoked", [False, True], ids=["unknown", "revoked"])
async def test_unknown_or_revoked_client_is_rejected(
    store: Store, db: AsyncSession, revoked: bool
) -> None:
    client_id = (await make_client(db, revoked=True)).client_id if revoked else "nope"

    with pytest.raises(AuthenticationError):
        await _authenticator(store).authenticate_request(
            form_request({"client_id": client_id})
        )


async def test_missing_client_id_is_rejected(store: Store, db: AsyncSession) -> None:
    with pytest.raises(AuthenticationError) as caught:
        await _authenticator(store).authenticate_request(form_request({}))

    assert caught.value.message == "Missing client_id"

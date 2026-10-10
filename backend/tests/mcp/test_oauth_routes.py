"""The OAuth routes and discovery documents over HTTP (D1, D2, D8, D9, D10, D29)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, func, select
from structlog.testing import capture_logs

from app.config import get_settings
from app.identity import ApiToken, OAuthAuthorizationRequest, OAuthClient, User
from app.identity.api_tokens import hash_secret
from app.identity.repository import CredentialRepository
from app.mcp.auth import AtlasTokenVerifier
from tests.access_helpers import make_user
from tests.identity.credential_helpers import LOOPBACK_REDIRECT, assert_no_secret
from tests.identity.oauth_helpers import HOSTED_REDIRECT
from tests.mcp.oauth_client import (
    BASE,
    CONSENT,
    ISSUER,
    RESOURCE,
    Store,
    age_rotation,
    approve_directly,
    authorize,
    authorize_response,
    exchange,
    http,
    oauth_store,
    oauth_test_app,
    pkce,
    refresh,
    register,
    revoke,
    tokens_for,
)

AS_ROOT = "/.well-known/oauth-authorization-server/mcp-server"
AS_ISSUER = "/mcp-server/.well-known/oauth-authorization-server"
PRM = "/.well-known/oauth-protected-resource/mcp-server/mcp"


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[Store]:
    async with oauth_store(tmp_path) as opened:
        yield opened


@pytest.fixture
def db(store: Store) -> AsyncSession:
    """This module's own database (no demo seed), shared with the routes."""
    return store.db


async def _user(db: AsyncSession) -> User:
    return await make_user(db, f"u-{uuid4().hex[:8]}@yougotagift.com", role="analyst")


async def _row(db: AsyncSession, raw: str) -> ApiToken:
    return (
        await db.execute(
            select(ApiToken)
            .where(col(ApiToken.token_hash) == hash_secret(raw))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _request_rows(db: AsyncSession) -> int:
    return (
        await db.execute(select(func.count()).select_from(OAuthAuthorizationRequest))
    ).scalar_one()


# ---- discovery --------------------------------------------------------------------


async def test_as_metadata_advertises_none_s256_and_no_scopes(
    store: Store, db: AsyncSession
) -> None:
    async with http(oauth_test_app(store).app) as client:
        body = (await client.get(AS_ROOT)).json()

    assert body["issuer"] == ISSUER
    assert body["authorization_endpoint"] == f"{ISSUER}/authorize"
    assert body["token_endpoint"] == f"{ISSUER}/token"
    assert body["registration_endpoint"] == f"{ISSUER}/register"
    assert body["revocation_endpoint"] == f"{ISSUER}/revoke"
    assert "none" in body["token_endpoint_auth_methods_supported"]
    assert "none" in body["revocation_endpoint_auth_methods_supported"]
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert body["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert "scopes_supported" not in body
    assert "client_id_metadata_document_supported" not in body


async def test_as_metadata_is_served_at_both_paths(
    store: Store, db: AsyncSession
) -> None:
    async with http(oauth_test_app(store).app) as client:
        root = await client.get(AS_ROOT)
        issuer_relative = await client.get(AS_ISSUER)

    assert root.status_code == issuer_relative.status_code == 200
    assert root.json() == issuer_relative.json()
    assert root.headers["access-control-allow-origin"] == "*"


async def test_protected_resource_metadata(store: Store, db: AsyncSession) -> None:
    async with http(oauth_test_app(store).app) as client:
        response = await client.get(PRM)

    body = response.json()
    assert body["resource"] == RESOURCE
    assert body["authorization_servers"] == [ISSUER]
    assert body["bearer_methods_supported"] == ["header"]
    assert "scopes_supported" not in body
    assert response.headers["cache-control"] == "public, max-age=300"


@pytest.mark.parametrize("path", [PRM, AS_ROOT])
async def test_root_discovery_answers_cors_preflight(
    store: Store, db: AsyncSession, path: str
) -> None:
    async with http(oauth_test_app(store).app) as client:
        response = await client.options(
            path,
            headers={
                "Origin": "https://claude.ai",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "mcp-protocol-version",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "GET" in response.headers["access-control-allow-methods"]
    assert (
        "mcp-protocol-version"
        in response.headers["access-control-allow-headers"].lower()
    )


async def test_discovery_follows_atlas_public_url(
    store: Store, db: AsyncSession
) -> None:
    public = "https://atlas.example.com"
    settings = get_settings().model_copy(update={"atlas_public_url": public})

    async with http(oauth_test_app(store, settings).app) as client:
        prm = (await client.get(PRM)).json()
        root = (await client.get(AS_ROOT)).json()
        issuer_relative = (await client.get(AS_ISSUER)).json()

    assert prm["resource"] == f"{public}/mcp-server/mcp"
    assert prm["authorization_servers"] == [f"{public}/mcp-server"]
    assert root == issuer_relative
    assert root["issuer"] == f"{public}/mcp-server"
    assert root["token_endpoint"] == f"{public}/mcp-server/token"


# ---- registration -----------------------------------------------------------------


async def test_register_public_client_gets_no_secret(
    store: Store, db: AsyncSession
) -> None:
    async with http(oauth_test_app(store).app) as client:
        body = await register(client)

    assert body["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in body
    assert body["redirect_uris"] == [LOOPBACK_REDIRECT]


async def test_register_confidential_client_sees_its_secret_once(
    store: Store, db: AsyncSession
) -> None:
    async with http(oauth_test_app(store).app) as client:
        body = await register(client, auth_method="client_secret_post")

    secret = body["client_secret"]
    row = (
        await db.execute(
            select(OAuthClient).where(col(OAuthClient.client_id) == body["client_id"])
        )
    ).scalar_one()
    assert row.client_secret_hash == hash_secret(secret)
    assert_no_secret(secret, row.model_dump())


@pytest.mark.parametrize(
    "redirect",
    ["http://localhost:35535/oauth/callback", HOSTED_REDIRECT],
    ids=["desktop-loopback", "claude-ai"],
)
async def test_register_accepts_the_known_callbacks(
    store: Store, db: AsyncSession, redirect: str
) -> None:
    async with http(oauth_test_app(store).app) as client:
        body = await register(client, redirect=redirect)

    assert body["redirect_uris"] == [redirect]


async def test_register_rejects_a_non_allowlisted_redirect(
    store: Store, db: AsyncSession
) -> None:
    async with http(oauth_test_app(store).app) as client:
        response = await client.post(
            "/mcp-server/register",
            json={
                "redirect_uris": ["https://evil.example/cb"],
                "token_endpoint_auth_method": "none",
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


# ---- authorize --------------------------------------------------------------------


async def test_authorize_redirects_to_consent(store: Store, db: AsyncSession) -> None:
    async with http(oauth_test_app(store).app) as client:
        client_id = (await register(client))["client_id"]
        response = await authorize_response(client, client_id, pkce()[1])

    assert response.status_code == 302
    assert response.headers["location"].startswith(f"{CONSENT}?txn=")
    assert response.headers["cache-control"] == "no-store"
    txn = parse_qs(urlsplit(response.headers["location"]).query)["txn"][0]
    row = await db.get(OAuthAuthorizationRequest, hash_secret(txn))
    assert row is not None
    assert row.resource == RESOURCE
    assert_no_secret(txn, row.model_dump())


async def test_authorize_refuses_plain_pkce(store: Store, db: AsyncSession) -> None:
    async with http(oauth_test_app(store).app) as client:
        client_id = (await register(client))["client_id"]
        response = await authorize_response(client, client_id, "a" * 43, method="plain")

    location = response.headers.get("location", "")
    assert response.status_code == 302
    assert location.startswith(LOOPBACK_REDIRECT)
    assert parse_qs(urlsplit(location).query)["error"] == ["invalid_request"]
    assert await _request_rows(db) == 0


async def test_authorize_refuses_a_missing_challenge(
    store: Store, db: AsyncSession
) -> None:
    async with http(oauth_test_app(store).app) as client:
        client_id = (await register(client))["client_id"]
        response = await authorize_response(client, client_id, None)

    assert response.status_code in (302, 400)
    assert "invalid_request" in (response.headers.get("location", "") + response.text)
    assert await _request_rows(db) == 0


async def test_authorize_refuses_an_unregistered_redirect_without_redirecting(
    store: Store,
    db: AsyncSession,
) -> None:
    async with http(oauth_test_app(store).app) as client:
        client_id = (await register(client))["client_id"]
        response = await authorize_response(
            client, client_id, pkce()[1], redirect="http://localhost:9999/other"
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert await _request_rows(db) == 0


async def test_authorize_foreign_resource_redirects_invalid_request_with_state(
    store: Store,
    db: AsyncSession,
) -> None:
    async with http(oauth_test_app(store).app) as client:
        client_id = (await register(client))["client_id"]
        response = await authorize_response(
            client,
            client_id,
            pkce()[1],
            state="keep-me",
            resource="https://evil.example/mcp",
        )

    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert response.status_code == 302
    assert query["error"] == ["invalid_request"]
    assert query["state"] == ["keep-me"]


async def test_authorize_internal_failure_is_generic(
    store: Store, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = oauth_test_app(store)

    async def broken(*_args: object) -> None:
        raise RuntimeError("database exploded")

    async with http(app.app) as client:
        client_id = (await register(client))["client_id"]
        monkeypatch.setattr(app.provider, "get_client", broken)
        response = await authorize_response(client, client_id, pkce()[1])

    assert response.status_code == 500
    assert response.json()["error"] == "server_error"
    assert "exploded" not in response.text


# ---- token ------------------------------------------------------------------------


async def test_token_endpoint_requires_form_encoding(
    store: Store, db: AsyncSession
) -> None:
    async with http(oauth_test_app(store).app) as client:
        client_id = (await register(client))["client_id"]
        response = await client.post(
            "/mcp-server/token",
            json={"grant_type": "authorization_code", "client_id": client_id},
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert response.headers["cache-control"] == "no-store"


async def test_wrong_pkce_verifier_is_invalid_grant(
    store: Store, db: AsyncSession
) -> None:
    user = await _user(db)
    async with http(oauth_test_app(store).app) as client:
        client_id = (await register(client))["client_id"]
        verifier, challenge = pkce()
        code, _ = await approve_directly(
            store, await authorize(client, client_id, challenge), user
        )
        response = await exchange(client, client_id, code, pkce()[0])
        # A failed PKCE check does not burn the code: the real verifier still works.
        retried = await exchange(client, client_id, code, verifier)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
    assert_no_secret(code, response.text)
    assert retried.status_code == 200, retried.text


async def test_missing_pkce_verifier_is_invalid_request(
    store: Store, db: AsyncSession
) -> None:
    user = await _user(db)
    async with http(oauth_test_app(store).app) as client:
        client_id = (await register(client))["client_id"]
        code, _ = await approve_directly(
            store, await authorize(client, client_id, pkce()[1]), user
        )
        response = await exchange(client, client_id, code, None)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert_no_secret(code, response.text)


async def test_token_redirect_uri_must_match(store: Store, db: AsyncSession) -> None:
    user = await _user(db)
    async with http(oauth_test_app(store).app) as client:
        client_id = (await register(client))["client_id"]
        verifier, challenge = pkce()
        code, _ = await approve_directly(
            store, await authorize(client, client_id, challenge), user
        )
        response = await exchange(
            client, client_id, code, verifier, redirect="http://localhost:1/other"
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


async def test_redirect_compares_in_canonical_form(
    store: Store, db: AsyncSession
) -> None:
    """A client may register `http://127.0.0.1:33418` and send it back with the
    trailing slash: both sides are compared as str(AnyUrl)."""
    user = await _user(db)
    bare = "http://127.0.0.1:33418"
    async with http(oauth_test_app(store).app) as client:
        client_id = (await register(client, redirect=bare))["client_id"]
        verifier, challenge = pkce()
        code, _ = await approve_directly(
            store,
            await authorize(client, client_id, challenge, redirect=f"{bare}/"),
            user,
        )
        response = await exchange(client, client_id, code, verifier, redirect=bare)

    assert response.status_code == 200, response.text


async def test_confidential_client_must_present_its_secret(
    store: Store, db: AsyncSession
) -> None:
    user = await _user(db)
    async with http(oauth_test_app(store).app) as client:
        registered = await register(client, auth_method="client_secret_post")
        client_id, secret = registered["client_id"], registered["client_secret"]
        verifier, challenge = pkce()
        code, _ = await approve_directly(
            store, await authorize(client, client_id, challenge), user
        )
        wrong = await exchange(client, client_id, code, verifier, secret=secret[::-1])
        right = await exchange(client, client_id, code, verifier, secret=secret)

    assert wrong.status_code == 401
    assert wrong.json()["error"] == "unauthorized_client"
    assert_no_secret(secret, wrong.text)
    assert right.status_code == 200, right.text


async def test_token_internal_failure_is_generic(
    store: Store, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _user(db)
    app = oauth_test_app(store)

    async def broken(*_args: object) -> None:
        raise RuntimeError("database exploded")

    async with http(app.app) as client:
        client_id = (await register(client))["client_id"]
        verifier, challenge = pkce()
        code, _ = await approve_directly(
            store, await authorize(client, client_id, challenge), user
        )
        monkeypatch.setattr(app.provider, "load_authorization_code", broken)
        response = await exchange(client, client_id, code, verifier)

    assert response.status_code == 500
    assert response.json()["error"] == "server_error"
    assert response.headers["cache-control"] == "no-store"
    assert_no_secret(code, response.text)


SERVER_ERROR = {
    "error": "server_error",
    "error_description": "The authorization server could not handle the request.",
}


async def test_a_transient_refresh_failure_is_server_error_and_the_token_survives(
    store: Store, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed eligibility check is not invalid_grant (a client would drop a good
    refresh token): a fixed server_error body, nothing leaked, and the same
    refresh token works once the check recovers."""
    user = await _user(db)
    app = oauth_test_app(store)

    async def broken(*_args: object) -> None:
        raise RuntimeError("policy store down: SELECT * FROM grants")

    async with http(app.app) as client:
        client_id, tokens = await tokens_for(store, client, user)
        with monkeypatch.context() as patched:
            patched.setattr("app.mcp.oauth_provider.policy_for", broken)
            failed = await refresh(client, client_id, tokens["refresh_token"])
        retried = await refresh(client, client_id, tokens["refresh_token"])

    assert failed.status_code == 500
    assert failed.json() == SERVER_ERROR
    assert failed.headers["cache-control"] == "no-store"
    assert "policy" not in failed.text
    assert "SELECT" not in failed.text
    assert_no_secret(tokens["refresh_token"], failed.text)
    assert retried.status_code == 200


async def test_a_database_error_during_refresh_is_server_error_without_sql(
    store: Store, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _user(db)
    app = oauth_test_app(store)

    async def broken(*_args: object) -> bool:
        raise DBAPIError(
            "UPDATE api_tokens SET revoked_at=$1", {}, Exception("deadlock detected")
        )

    async with http(app.app) as client:
        client_id, tokens = await tokens_for(store, client, user)
        with monkeypatch.context() as patched:
            patched.setattr(CredentialRepository, "mark_rotated", broken)
            failed = await refresh(client, client_id, tokens["refresh_token"])
        retried = await refresh(client, client_id, tokens["refresh_token"])

    assert failed.status_code == 500
    assert failed.json() == SERVER_ERROR
    for leak in ("UPDATE", "api_tokens", "deadlock"):
        assert leak not in failed.text
    assert retried.status_code == 200


# ---- revoke -----------------------------------------------------------------------


async def test_public_client_can_revoke_without_a_secret(
    store: Store, db: AsyncSession
) -> None:
    user = await _user(db)
    async with http(oauth_test_app(store).app) as client:
        client_id, tokens = await tokens_for(store, client, user)
        response = await revoke(
            client, client_id, tokens["refresh_token"], hint="refresh_token"
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert (
        await AtlasTokenVerifier(RESOURCE, store.sessions).verify_token(
            tokens["access_token"]
        )
        is None
    )


async def test_revoking_an_unknown_token_is_200(store: Store, db: AsyncSession) -> None:
    async with http(oauth_test_app(store).app) as client:
        client_id = (await register(client))["client_id"]
        response = await revoke(client, client_id, "atl_oat_" + "x" * 43)

    assert response.status_code == 200


async def test_revocation_by_another_client_is_a_no_op(
    store: Store, db: AsyncSession
) -> None:
    user = await _user(db)
    async with http(oauth_test_app(store).app) as client:
        _, tokens = await tokens_for(store, client, user)
        other = (await register(client))["client_id"]
        response = await revoke(client, other, tokens["access_token"])

    assert response.status_code == 200
    live = (
        await db.execute(
            select(func.count())
            .select_from(ApiToken)
            .where(col(ApiToken.revoked_at).is_(None))
        )
    ).scalar_one()
    assert live == 2
    assert (
        await AtlasTokenVerifier(RESOURCE, store.sessions).verify_token(
            tokens["access_token"]
        )
        is not None
    )


async def test_an_expired_access_token_can_still_revoke_its_family(
    store: Store, db: AsyncSession
) -> None:
    user = await _user(db)
    async with http(oauth_test_app(store).app) as client:
        client_id, tokens = await tokens_for(store, client, user)
        access = await _row(db, tokens["access_token"])
        await db.execute(
            update(ApiToken)
            .where(col(ApiToken.id) == access.id)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=5))
        )
        await db.commit()
        response = await revoke(client, client_id, tokens["access_token"])
        refreshed = await refresh(client, client_id, tokens["refresh_token"])

    assert response.status_code == 200
    assert refreshed.status_code == 400
    assert refreshed.json()["error"] == "invalid_grant"
    after = await _row(db, tokens["access_token"])
    assert after.revoked_reason == "oauth_revoke"
    assert after.last_used_at == access.last_used_at  # never touched by the lookup


async def test_unknown_token_type_hints_are_ignored(
    store: Store, db: AsyncSession
) -> None:
    user = await _user(db)
    async with http(oauth_test_app(store).app) as client:
        client_id, tokens = await tokens_for(store, client, user)
        response = await revoke(
            client, client_id, tokens["refresh_token"], hint="device_code"
        )

    assert response.status_code == 200
    assert (await _row(db, tokens["refresh_token"])).revoked_at is not None


async def test_revoke_requires_form_encoding_and_a_token(
    store: Store, db: AsyncSession
) -> None:
    async with http(oauth_test_app(store).app) as client:
        client_id = (await register(client))["client_id"]
        as_json = await client.post(
            "/mcp-server/revoke", json={"client_id": client_id, "token": "x"}
        )
        no_token = await client.post(
            "/mcp-server/revoke", data={"client_id": client_id}
        )

    assert as_json.status_code == 400
    assert no_token.status_code == 400
    assert no_token.json()["error"] == "invalid_request"


async def test_revoke_by_an_unauthenticated_client_is_401(
    store: Store, db: AsyncSession
) -> None:
    async with http(oauth_test_app(store).app) as client:
        response = await revoke(client, "no-such-client", "atl_oat_" + "x" * 43)

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized_client"


def test_base_url_matches_the_default_public_url() -> None:
    assert get_settings().atlas_public_url == BASE


async def test_refresh_token_revoked_by_another_client_kills_its_family(
    store: Store, db: AsyncSession
) -> None:
    """Not a no-op, deliberately: a refresh token in another client's hands is
    theft evidence, and identity's load_refresh revokes the family on any
    cross-client presentation (as /token does). The revoke itself never happens
    on the presenter's behalf, and the answer is still 200."""
    user = await _user(db)
    async with http(oauth_test_app(store).app) as client:
        _, tokens = await tokens_for(store, client, user)
        other = (await register(client))["client_id"]
        response = await revoke(
            client, other, tokens["refresh_token"], hint="refresh_token"
        )

    assert response.status_code == 200
    reasons = {row.revoked_reason for row in await _family_rows(db)}
    assert reasons == {"cross_client"}


# ---- the whole flow over HTTP ------------------------------------------------------


async def _token_row(db: AsyncSession, raw: str) -> ApiToken:
    return (
        await db.execute(
            select(ApiToken)
            .where(col(ApiToken.token_hash) == hash_secret(raw))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _family_rows(db: AsyncSession) -> list[ApiToken]:
    rows = await db.execute(select(ApiToken).execution_options(populate_existing=True))
    return list(rows.scalars().all())


async def test_register_authorize_consent_token_refresh_reuse_revoke(
    store: Store, db: AsyncSession
) -> None:
    user = await _user(db)
    oauth = oauth_test_app(store)
    verify = oauth.verifier.verify_token
    async with http(oauth.app) as client:
        prm = (await client.get(PRM)).json()
        assert prm["authorization_servers"] == [ISSUER]
        meta = (await client.get(AS_ROOT)).json()
        assert meta["registration_endpoint"] == f"{ISSUER}/register"

        client_id = (await register(client))["client_id"]
        verifier, challenge = pkce()
        txn = await authorize(client, client_id, challenge, state="s-42")
        code, state = await approve_directly(store, txn, user)
        assert state == "s-42"

        issued = await exchange(client, client_id, code, verifier)
        assert issued.status_code == 200, issued.text
        assert issued.headers["cache-control"] == "no-store"
        first = issued.json()
        assert first["token_type"] == "Bearer"
        assert first["expires_in"] == 3600
        assert first["access_token"].startswith("atl_oat_")
        assert first["refresh_token"].startswith("atl_ort_")
        access = await verify(first["access_token"])
        assert access is not None
        assert access.subject == str(user.id)
        assert access.resource == RESOURCE

        rotated = await refresh(client, client_id, first["refresh_token"])
        assert rotated.status_code == 200, rotated.text
        second = rotated.json()
        assert second["refresh_token"] != first["refresh_token"]
        old = await _token_row(db, first["refresh_token"])
        assert old.revoked_reason == "rotated"

        await age_rotation(db, old.id, 31)  # past the 30 s grace: now it is reuse
        reused = await refresh(client, client_id, first["refresh_token"])
        assert reused.status_code == 400
        assert reused.json()["error"] == "invalid_grant"
        assert all(row.revoked_at is not None for row in await _family_rows(db))
        assert await verify(second["access_token"]) is None

        _, fresh = await tokens_for(store, client, user)  # a new consent works
        assert await verify(fresh["access_token"]) is not None
        revoked = await revoke(
            client, client_id, fresh["refresh_token"], hint="refresh_token"
        )

    assert revoked.status_code == 200
    assert await verify(fresh["access_token"]) is None


async def test_code_replay_over_http_revokes_the_tokens(
    store: Store, db: AsyncSession
) -> None:
    user = await _user(db)
    oauth = oauth_test_app(store)
    async with http(oauth.app) as client:
        client_id = (await register(client))["client_id"]
        verifier, challenge = pkce()
        code, _ = await approve_directly(
            store, await authorize(client, client_id, challenge), user
        )
        first = await exchange(client, client_id, code, verifier)
        replay = await exchange(client, client_id, code, verifier)

    assert first.status_code == 200
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"
    assert await oauth.verifier.verify_token(first.json()["access_token"]) is None


async def test_refresh_retry_within_grace_over_http(
    store: Store, db: AsyncSession
) -> None:
    user = await _user(db)
    async with http(oauth_test_app(store).app) as client:
        client_id, tokens = await tokens_for(store, client, user)
        once = await refresh(client, client_id, tokens["refresh_token"])
        twice = await refresh(client, client_id, tokens["refresh_token"])

    assert once.status_code == twice.status_code == 200, twice.text


async def test_refresh_from_another_client_is_invalid_grant_and_revokes(
    store: Store, db: AsyncSession
) -> None:
    user = await _user(db)
    oauth = oauth_test_app(store)
    async with http(oauth.app) as client:
        _, tokens = await tokens_for(store, client, user)
        thief = (await register(client))["client_id"]
        response = await refresh(client, thief, tokens["refresh_token"])

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
    assert await oauth.verifier.verify_token(tokens["access_token"]) is None


async def test_confidential_basic_client_over_http(
    store: Store, db: AsyncSession
) -> None:
    user = await _user(db)
    async with http(oauth_test_app(store).app) as client:
        registered = await register(client, auth_method="client_secret_basic")
        client_id, secret = registered["client_id"], registered["client_secret"]
        verifier, challenge = pkce()
        code, _ = await approve_directly(
            store, await authorize(client, client_id, challenge), user
        )
        unauthenticated = await exchange(client, client_id, code, verifier)
        response = await client.post(
            "/mcp-server/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": LOOPBACK_REDIRECT,
            },
            auth=(client_id, secret),
        )

    assert unauthenticated.status_code == 401
    assert response.status_code == 200, response.text


async def test_no_secret_in_logs_or_error_bodies(
    store: Store, db: AsyncSession
) -> None:
    user = await _user(db)
    secrets: list[str] = []
    failures: list[str] = []
    with capture_logs() as logs:
        async with http(oauth_test_app(store).app) as client:
            registered = await register(client, auth_method="client_secret_post")
            client_id, secret = registered["client_id"], registered["client_secret"]
            verifier, challenge = pkce()
            txn = await authorize(client, client_id, challenge)
            code, _ = await approve_directly(store, txn, user)
            bad_secret = await exchange(
                client, client_id, code, verifier, secret=secret[::-1] + "x"
            )
            bad_verifier = await exchange(
                client, client_id, code, pkce()[0], secret=secret
            )
            verifier2, challenge2 = pkce()
            code2, _ = await approve_directly(
                store, await authorize(client, client_id, challenge2), user
            )
            good = await exchange(client, client_id, code2, verifier2, secret=secret)
            tokens = good.json()
            replay = await exchange(client, client_id, code2, verifier2, secret=secret)
            dead = await refresh(
                client, client_id, tokens["refresh_token"], secret=secret
            )
            revoked = await revoke(
                client, client_id, tokens["access_token"], secret=secret
            )
            secrets = [
                secret,
                txn,
                code,
                code2,
                tokens["access_token"],
                tokens["refresh_token"],
            ]
            failures = [
                r.text for r in (bad_secret, bad_verifier, replay, dead) if r.is_error
            ]

    assert good.status_code == revoked.status_code == 200
    assert len(failures) == 4
    for raw in secrets:
        assert_no_secret(raw, logs, *failures)

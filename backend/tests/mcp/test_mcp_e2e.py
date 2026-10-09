"""The MCP surface end to end over HTTP: discovery, OAuth, PATs, service tokens,
revocation, audience, DNS rebinding and secrecy (spec §4.1, §4.3, §13)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select
from structlog.testing import capture_logs

from app.access.schemas import UserUpdate
from app.config import Settings, get_settings
from app.identity import (
    REVOKED_BY_USER,
    REVOKED_USER_DISABLED,
    ApiToken,
    TokenKind,
    User,
    hash_secret,
)
from app.models.audit import AtlasAuditLog
from tests.access_helpers import actor_with, add_grant, admin_for, make_user
from tests.identity.credential_helpers import (
    assert_no_secret,
    insert_token,
    make_client,
)
from tests.identity.oauth_helpers import query_param
from tests.mcp.api_helpers import as_user
from tests.mcp.mcp_rpc import (
    BASE,
    INITIALIZE,
    call_tool,
    post_rpc,
    rpc,
    rpc_result,
    serving,
    tool_names,
)
from tests.mcp.oauth_client import (
    age_rotation,
    authorize,
    exchange,
    pkce,
    refresh,
    register,
)

PRM_URL = f"{BASE}/.well-known/oauth-protected-resource/mcp-server/mcp"
METRIC_AND_CATALOG_TOOLS = {
    "list_metrics",
    "search_atlas",
    "describe_entity",
    "query_metric",
    "metric_breakdown",
    "compare_periods",
}


async def _analyst(db: AsyncSession, grant: str = "demo/order/*") -> User:
    user = await make_user(db, f"u-{uuid4().hex[:8]}@yougotagift.com", role="analyst")
    await add_grant(db, user, grant)
    return user


async def _pat(db: AsyncSession, user: User) -> str:
    _, raw = await insert_token(db, user, TokenKind.PAT)
    return raw


async def _row(db: AsyncSession, raw: str) -> ApiToken:
    return (
        await db.execute(
            select(ApiToken)
            .where(col(ApiToken.token_hash) == hash_secret(raw))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _audit_rows(db: AsyncSession, user: User) -> list[AtlasAuditLog]:
    rows = await db.execute(
        select(AtlasAuditLog)
        .where(col(AtlasAuditLog.user_id) == user.id)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


async def _oauth_tokens(
    app: FastAPI, client: httpx.AsyncClient, user: User
) -> tuple[str, dict[str, Any]]:
    """Register -> authorize -> consent over HTTP as `user` -> token."""
    client_id = (await register(client))["client_id"]
    verifier, challenge = pkce()
    txn = await authorize(client, client_id, challenge)
    as_user(app, user)
    consent = await client.post(
        "/api/v1/oauth/consent", json={"transaction_id": txn, "decision": "approve"}
    )
    assert consent.status_code == 200, consent.text
    code = query_param(consent.json()["redirect_to"], "code")
    response = await exchange(client, client_id, code, verifier)
    assert response.status_code == 200, response.text
    return client_id, response.json()


@pytest.fixture
def shared_token_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ATLAS_MCP_TOKEN", "s3cret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---- unauthenticated -----------------------------------------------------------------


async def test_unauthenticated_call_is_401_with_resource_metadata(db) -> None:
    async with serving() as (_, client):
        response = await post_rpc(client, None, "tools/list")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == (
        'Bearer error="invalid_token", error_description="Authentication required", '
        f'resource_metadata="{PRM_URL}"'
    )
    assert response.json()["error"] == "invalid_token"


# ---- OAuth (spec §4.3) ---------------------------------------------------------------


async def test_oauth_flow_end_to_end(db) -> None:
    user = await _analyst(db)
    async with serving() as (app, client):
        # Discovery, from the 401 header down to the authorization server.
        challenge = await post_rpc(client, None, "initialize", INITIALIZE)
        assert challenge.status_code == 401
        prm_url = challenge.headers["www-authenticate"].split('resource_metadata="')[1]
        prm = (await client.get(urlsplit(prm_url.rstrip('"')).path)).json()
        assert prm["resource"] == f"{BASE}/mcp-server/mcp"
        (issuer,) = prm["authorization_servers"]
        issuer_path = urlsplit(issuer).path
        metadata = (
            await client.get(f"/.well-known/oauth-authorization-server{issuer_path}")
        ).json()
        assert metadata["issuer"] == issuer
        assert metadata["registration_endpoint"] == f"{issuer}/register"

        client_id, tokens = await _oauth_tokens(app, client, user)
        access = tokens["access_token"]

        initialized = await rpc(client, access, "initialize", INITIALIZE)
        assert initialized["serverInfo"]["name"] == "ygg-atlas"
        assert await tool_names(client, access) == METRIC_AND_CATALOG_TOOLS
        listed = await call_tool(client, access, "list_metrics")
        assert "revenue" in {m["id"] for m in listed["sources"][0]["metrics"]}

        (audit,) = await _audit_rows(db, user)
        assert audit.surface == "mcp"
        assert audit.auth_method == "oauth"
        assert audit.token_id == (await _row(db, access)).id
        assert audit.client_id == client_id

        # Rotation, then reuse of the old refresh token after the grace window.
        rotated = await refresh(client, client_id, tokens["refresh_token"])
        assert rotated.status_code == 200, rotated.text
        new_access = rotated.json()["access_token"]
        assert await tool_names(client, new_access) == METRIC_AND_CATALOG_TOOLS
        await age_rotation(db, (await _row(db, tokens["refresh_token"])).id, 60)
        reused = await refresh(client, client_id, tokens["refresh_token"])
        assert reused.status_code == 400
        assert reused.json()["error"] == "invalid_grant"
        assert (await post_rpc(client, new_access, "tools/list")).status_code == 401

        # The user simply authorizes again.
        _, again = await _oauth_tokens(app, client, user)
        assert await tool_names(client, again["access_token"]) == (
            METRIC_AND_CATALOG_TOOLS
        )


async def test_disconnected_app_is_401_then_reauth_works(db) -> None:
    user = await _analyst(db)
    async with serving() as (app, client):
        _, tokens = await _oauth_tokens(app, client, user)
        access = tokens["access_token"]
        family_id = (await _row(db, access)).family_id
        assert isinstance(family_id, UUID)

        disconnected = await client.delete(f"/api/v1/me/connected-apps/{family_id}")
        assert disconnected.status_code == 204
        assert (await post_rpc(client, access, "tools/list")).status_code == 401
        client_id = (await _row(db, access)).client_id or ""
        refused = await refresh(client, client_id, tokens["refresh_token"])
        assert refused.status_code == 400

        _, again = await _oauth_tokens(app, client, user)
        assert await tool_names(client, again["access_token"]) == (
            METRIC_AND_CATALOG_TOOLS
        )


async def test_mcp_door_ignores_auth_disabled(db) -> None:
    """D33: AUTH_DISABLED (on for the whole suite) gives REST a dev user, never MCP."""
    assert get_settings().auth_disabled
    async with serving() as (_, client):
        anonymous = await post_rpc(client, None, "tools/list")
        garbage = await post_rpc(client, "dev", "tools/list")
    assert anonymous.status_code == garbage.status_code == 401


async def test_token_for_another_audience_is_401(db) -> None:
    user = await _analyst(db)
    oauth_client = await make_client(db)
    _, raw = await insert_token(
        db,
        user,
        TokenKind.OAUTH_ACCESS,
        client_id=oauth_client.client_id,
        family_id=uuid4(),
        audience="https://other.example/mcp",
    )
    async with serving() as (_, client):
        assert (await post_rpc(client, raw, "tools/list")).status_code == 401


# ---- personal and service tokens -----------------------------------------------------


async def test_pat_via_header_calls_tools(db) -> None:
    user = await _analyst(db)
    raw = await _pat(db, user)
    async with serving() as (_, client):
        assert await tool_names(client, raw) == METRIC_AND_CATALOG_TOOLS
        today = datetime.now(UTC).date()
        result = await call_tool(
            client,
            raw,
            "query_metric",
            {
                "metric_id": "orders_count",
                "start_date": (today - timedelta(days=30)).isoformat(),
                "end_date": today.isoformat(),
            },
        )

    assert "error" not in result, result
    assert result["value"] > 0
    (audit,) = await _audit_rows(db, user)
    assert (audit.auth_method, audit.surface, audit.tool) == (
        "pat",
        "mcp",
        "query_metric",
    )
    assert audit.token_id == (await _row(db, raw)).id
    assert audit.client_id is None


async def test_service_token_calls_tools_as_the_service_account(db) -> None:
    service = await make_user(
        db, "svc-nightly@atlas.internal", role="analyst", kind="service"
    )
    await add_grant(db, service, "demo/order/*")
    _, raw = await insert_token(db, service, TokenKind.SERVICE)
    async with serving() as (_, client):
        result = await call_tool(client, raw, "list_metrics")

    assert result["sources"]
    (audit,) = await _audit_rows(db, service)
    assert audit.auth_method == "service"
    assert audit.token_id == (await _row(db, raw)).id


async def test_a_pat_is_never_a_service_token(db) -> None:
    service = await make_user(
        db, "svc-x@atlas.internal", role="analyst", kind="service"
    )
    _, raw = await insert_token(db, service, TokenKind.PAT)  # wrong kind for a service
    async with serving() as (_, client):
        assert (await post_rpc(client, raw, "tools/list")).status_code == 401


async def test_revoked_pat_is_401_on_the_next_request(db) -> None:
    user = await _analyst(db)
    raw = await _pat(db, user)
    async with serving() as (_, client):
        assert (await post_rpc(client, raw, "tools/list")).status_code == 200
        row = await _row(db, raw)
        row.revoked_at = row.created_at
        row.revoked_reason = REVOKED_BY_USER
        await db.commit()
        assert (await post_rpc(client, raw, "tools/list")).status_code == 401


async def test_user_disabled_mid_session_is_401(db) -> None:
    user = await _analyst(db)
    raw = await _pat(db, user)
    actor = await actor_with(db)
    async with serving() as (_, client):
        assert (await post_rpc(client, raw, "tools/list")).status_code == 200
        await admin_for(db).update_user(actor, user.id, UserUpdate(status="disabled"))
        assert (await post_rpc(client, raw, "tools/list")).status_code == 401

    assert (await _row(db, raw)).revoked_reason == REVOKED_USER_DISABLED


async def test_user_without_mcp_use_sees_no_tools_and_a_denial(db) -> None:
    viewer = await make_user(db, "viewer@yougotagift.com", role="viewer")
    await add_grant(db, viewer, "*")
    raw = await _pat(db, viewer)
    async with serving() as (_, client):
        listed = await post_rpc(client, raw, "tools/list")
        called = await post_rpc(
            client, raw, "tools/call", {"name": "list_metrics", "arguments": {}}
        )

    assert listed.status_code == called.status_code == 200  # D31: never a 403
    assert rpc_result(listed)["tools"] == []
    text = rpc_result(called)["content"][0]["text"]
    assert "mcp:use" in text


# ---- the shared token is retired (D17) -----------------------------------------------


async def test_the_shared_token_is_gone(db, shared_token_env: None) -> None:
    assert not hasattr(get_settings(), "atlas_mcp_token")
    async with serving() as (_, client):
        response = await post_rpc(client, "s3cret", "tools/list")
    assert response.status_code == 401


# ---- DNS rebinding (D26) -------------------------------------------------------------


async def test_host_header_without_port_is_accepted_and_foreign_host_is_421(
    db,
) -> None:
    raw = await _pat(db, await _analyst(db))
    async with serving() as (_, client):
        bare = await post_rpc(client, raw, "tools/list", headers={"Host": "localhost"})
        foreign = await post_rpc(
            client, raw, "tools/list", headers={"Host": "evil.example"}
        )
    assert bare.status_code == 200
    assert foreign.status_code == 421


async def test_the_public_host_is_accepted_without_its_port(db) -> None:
    settings = Settings.model_validate(
        get_settings().model_dump() | {"atlas_public_url": "https://atlas.example.com"}
    )
    raw = await _pat(db, await _analyst(db))
    async with serving(settings) as (_, client):
        response = await post_rpc(
            client, raw, "tools/list", headers={"Host": "atlas.example.com"}
        )
    assert response.status_code == 200


# ---- secrecy (conventions, invariant 1) ----------------------------------------------


async def test_no_secret_in_logs_audit_or_bodies_end_to_end(db) -> None:
    user = await _analyst(db)
    pat = await _pat(db, user)
    bodies: list[str] = []
    with capture_logs() as logs:
        async with serving() as (app, client):
            bodies.append((await post_rpc(client, pat, "tools/list")).text)
            bodies.append(
                (
                    await post_rpc(
                        client,
                        pat,
                        "tools/call",
                        {"name": "list_metrics", "arguments": {}},
                    )
                ).text
            )
            _, tokens = await _oauth_tokens(app, client, user)
            access = tokens["access_token"]
            bodies.append((await post_rpc(client, access, "tools/list")).text)
            bodies.append((await post_rpc(client, access + "x", "tools/list")).text)

    audit = [
        {"arguments": row.arguments, "error": row.error}
        for row in await _audit_rows(db, user)
    ]
    for secret in (pat, access, tokens["refresh_token"]):
        assert_no_secret(secret, logs, audit, *bodies)

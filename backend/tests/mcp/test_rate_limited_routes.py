"""Rate limits as wired into the real routes (D16, ruling E1). Budgets are pre-spent
through the process-wide limiters so each test makes only a few real requests;
tests/mcp/conftest.py resets the limiters around every test."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.identity import TokenKind, User
from app.identity.api_tokens import mint
from app.mcp.ratelimit import (
    AUTHORIZE,
    BEARER_FAILURES,
    MCP_CALLS,
    REGISTER,
    REVOKE,
    TOKEN,
    RateLimitPolicy,
    limiter,
)
from tests.access_helpers import add_grant, make_user
from tests.identity.credential_helpers import assert_no_secret, insert_token
from tests.mcp.api_helpers import as_user
from tests.mcp.mcp_rpc import post_rpc, serving
from tests.mcp.oauth_client import authorize_response, pkce, register

PUBLIC_PEER = "8.8.4.4"
PRIVATE_PEER = "172.18.0.5"  # the nginx container on the compose network
CODE = "c0de" * 11  # a would-be authorization code; must never be echoed


async def _analyst(db: AsyncSession) -> User:
    user = await make_user(db, f"u-{uuid4().hex[:8]}@yougotagift.com", role="analyst")
    await add_grant(db, user, "*")
    return user


def _spend(policy: RateLimitPolicy, key: str, hits: int) -> None:
    for _ in range(hits):
        assert limiter(policy).hit(key).allowed


def _token_form() -> dict[str, str]:
    return {
        "grant_type": "authorization_code",
        "client_id": "nobody",
        "code": CODE,
        "code_verifier": "v" * 43,
    }


async def test_token_endpoint_429_after_30_per_minute(db) -> None:
    _spend(TOKEN, PUBLIC_PEER, 29)
    async with serving(peer=PUBLIC_PEER) as (_, client):
        last = await client.post("/mcp-server/token", data=_token_form())
        refused = await client.post(
            "/mcp-server/token",
            data=_token_form(),
            headers={"Origin": "https://claude.ai"},
        )

    assert last.status_code != 429
    assert refused.status_code == 429
    assert refused.headers["retry-after"]
    assert refused.json()["error"] == "rate_limited"
    # The limit sits inside CORS, so a browser client can read the refusal.
    assert refused.headers["access-control-allow-origin"] == "*"


async def test_authorize_429_after_30_per_minute(db) -> None:
    _spend(AUTHORIZE, PUBLIC_PEER, 29)
    async with serving(peer=PUBLIC_PEER) as (_, client):
        client_id = (await register(client))["client_id"]
        _, challenge = pkce()
        last = await authorize_response(client, client_id, challenge)
        refused = await authorize_response(client, client_id, challenge)

    assert last.status_code == 302
    assert refused.status_code == 429


async def test_register_429_after_10_per_hour(db) -> None:
    _spend(REGISTER, PUBLIC_PEER, 9)
    async with serving(peer=PUBLIC_PEER) as (_, client):
        await register(client)
        refused = await client.post(
            "/mcp-server/register", json={"redirect_uris": ["http://localhost:1/cb"]}
        )

    assert refused.status_code == 429
    assert 3500 < int(refused.headers["retry-after"]) <= 3600


async def test_revoke_429_after_30_per_minute(db) -> None:
    _spend(REVOKE, PUBLIC_PEER, 29)
    async with serving(peer=PUBLIC_PEER) as (_, client):
        client_id = (await register(client))["client_id"]
        form = {"client_id": client_id, "token": "atl_oat_" + "x" * 43}
        last = await client.post("/mcp-server/revoke", data=form)
        refused = await client.post("/mcp-server/revoke", data=form)

    assert last.status_code == 200
    assert refused.status_code == 429
    assert refused.headers["retry-after"]


async def test_per_source_limits_are_shared_behind_a_proxy(db) -> None:
    """Behind nginx every caller is one private peer: the budget is global (C15)."""
    _spend(TOKEN, "unknown", 30)
    async with serving(peer=PRIVATE_PEER) as (_, client):
        refused = await client.post("/mcp-server/token", data=_token_form())
    assert refused.status_code == 429


async def test_mcp_calls_429_after_120_per_token(db) -> None:
    user = await _analyst(db)
    row, raw = await insert_token(db, user, TokenKind.PAT)
    _, other = await insert_token(db, user, TokenKind.PAT)
    _spend(MCP_CALLS, str(row.id), 119)
    async with serving() as (_, client):
        last = await post_rpc(client, raw, "tools/list")
        refused = await post_rpc(client, raw, "tools/list")
        unaffected = await post_rpc(client, other, "tools/list")

    assert last.status_code == 200
    assert refused.status_code == 429
    assert refused.headers["retry-after"]
    assert unaffected.status_code == 200
    assert_no_secret(raw, refused.text, dict(refused.headers))


async def test_failed_bearers_429_after_20_per_source(db) -> None:
    good = (await insert_token(db, await _analyst(db), TokenKind.PAT))[1]
    async with serving(peer=PUBLIC_PEER) as (_, client):
        for _ in range(20):
            bad = await post_rpc(client, mint(TokenKind.PAT), "tools/list")
            assert bad.status_code == 401
        blocked = await post_rpc(client, good, "tools/list")

    assert blocked.status_code == 429
    assert limiter(BEARER_FAILURES).peek(PUBLIC_PEER).allowed is False


async def test_expired_bearers_are_never_counted_as_guessing(db) -> None:
    user = await _analyst(db)
    _, expired = await insert_token(
        db, user, TokenKind.PAT, expires_in=timedelta(seconds=-5)
    )
    good = (await insert_token(db, user, TokenKind.PAT))[1]
    async with serving(peer=PUBLIC_PEER) as (_, client):
        for _ in range(25):
            assert (await post_rpc(client, expired, "tools/list")).status_code == 401
        assert (await post_rpc(client, good, "tools/list")).status_code == 200


async def test_failed_bearers_from_a_private_peer_are_never_blocked(db) -> None:
    good = (await insert_token(db, await _analyst(db), TokenKind.PAT))[1]
    async with serving(peer=PRIVATE_PEER) as (_, client):
        for _ in range(25):
            bad = await post_rpc(client, mint(TokenKind.PAT), "tools/list")
            assert bad.status_code == 401
        assert (await post_rpc(client, good, "tools/list")).status_code == 200


async def test_consent_429_after_10_per_user(db) -> None:
    user, other = await _analyst(db), await _analyst(db)
    async with serving() as (app, client):
        as_user(app, user)
        for _ in range(10):
            gone = await client.get("/api/v1/oauth/consent/" + "t" * 43)
            assert gone.status_code == 404
        refused = await client.post(
            "/api/v1/oauth/consent",
            json={"transaction_id": "t" * 43, "decision": "approve"},
        )
        as_user(app, other)
        unaffected = await client.get("/api/v1/oauth/consent/" + "t" * 43)

    assert refused.status_code == 429
    assert refused.headers["retry-after"]
    assert refused.json()["detail"]["error"] == "rate_limited"
    assert unaffected.status_code == 404


async def test_429_has_retry_after_and_no_secret(db) -> None:
    _spend(TOKEN, PUBLIC_PEER, 30)
    async with serving(peer=PUBLIC_PEER) as (_, client):
        refused = await client.post("/mcp-server/token", data=_token_form())

    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) >= 1
    assert CODE not in refused.text
    assert PUBLIC_PEER not in refused.text

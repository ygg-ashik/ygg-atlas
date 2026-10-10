"""Smoke test of the real app (app.main.app) as deployed: lifespan and session
manager running, global CORS scoped away from the MCP and OAuth discovery paths.

One test only: an AtlasMCP session manager can run once per process (C9)."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app import main
from app.identity import TokenKind
from tests.access_helpers import add_grant, make_user
from tests.identity.credential_helpers import insert_token

BASE = "http://localhost:8080"
PRM = "/.well-known/oauth-protected-resource/mcp-server/mcp"
AS_METADATA = "/.well-known/oauth-authorization-server/mcp-server"
INSPECTOR = "http://localhost:6274"  # an origin outside CORS_ORIGINS
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _preflight(method: str) -> dict[str, str]:
    return {
        "Origin": INSPECTOR,
        "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": "content-type",
    }


async def test_the_real_app_serves_mcp_discovery_and_cors(db: AsyncSession) -> None:
    user = await make_user(db, "smoke@yougotagift.com", role="analyst")
    await add_grant(db, user, "*")
    _, pat = await insert_token(db, user, TokenKind.PAT)
    tools_list = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

    async with (
        main.app.router.lifespan_context(main.app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url=BASE
        ) as client,
    ):
        challenge = await client.post(
            "/mcp-server/mcp", json=tools_list, headers=MCP_HEADERS
        )
        prm = await client.get(PRM)
        metadata = await client.get(AS_METADATA)
        prm_preflight = await client.options(PRM, headers=_preflight("GET"))
        token_preflight = await client.options(
            "/mcp-server/token", headers=_preflight("POST")
        )
        listed = await client.post(
            "/mcp-server/mcp",
            json=tools_list,
            headers=MCP_HEADERS | {"Authorization": f"Bearer {pat}"},
        )
        # The SPA's own API keeps the global allowlist.
        api_preflight = await client.options(
            "/api/v1/me/tokens", headers=_preflight("GET")
        )

    assert challenge.status_code == 401
    assert challenge.headers["www-authenticate"] == (
        'Bearer error="invalid_token", error_description="Authentication required", '
        f'resource_metadata="{BASE}{PRM}"'
    )
    assert prm.status_code == 200
    assert prm.json()["resource"] == f"{BASE}/mcp-server/mcp"
    assert metadata.status_code == 200
    assert metadata.json()["issuer"] == f"{BASE}/mcp-server"
    for preflight in (prm_preflight, token_preflight):
        assert preflight.status_code == 200, preflight.text
        assert preflight.headers["access-control-allow-origin"] in ("*", INSPECTOR)
    assert listed.status_code == 200, listed.text
    assert '"list_metrics"' in listed.text
    assert api_preflight.status_code == 400

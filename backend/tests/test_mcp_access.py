"""MCP until phase 4: a shared token that is required, and a service user's grants."""

from collections.abc import Callable, Iterator

import pytest
from httpx import ASGITransport, AsyncClient, Response
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.config import get_settings
from app.mcp import server
from tests.access_helpers import add_grant, make_user

SERVICE_EMAIL = "mcp-shared@atlas.internal"


async def _get(headers: dict[str, str] | None = None) -> Response:
    async def ok(_request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(
        routes=[Route("/", ok)],
        middleware=[Middleware(server.BearerTokenMiddleware)],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get("/", headers=headers or {})


@pytest.fixture
def mcp_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
    def set_token(value: str) -> None:
        monkeypatch.setenv("ATLAS_MCP_TOKEN", value)
        get_settings.cache_clear()

    yield set_token
    get_settings.cache_clear()


async def test_mcp_is_off_without_a_token(mcp_token: Callable[[str], None]) -> None:
    mcp_token("")
    assert (await _get()).status_code == 503


async def test_the_token_must_match(mcp_token: Callable[[str], None]) -> None:
    mcp_token("s3cret")
    assert (await _get({"Authorization": "Bearer wrong"})).status_code == 401
    assert (await _get({"Authorization": "Bearer s3cret"})).status_code == 200


async def test_tools_run_as_the_service_user_with_its_grants(db) -> None:
    assert await server.run_tool("list_metrics", {}) == server.NOT_READY
    service = await make_user(db, SERVICE_EMAIL, role="analyst", kind="service")
    assert await server.run_tool("list_metrics", {}) == {"sources": []}

    await add_grant(db, service, "demo/order/*")

    result = await server.run_tool("list_metrics", {})
    assert "revenue" in {m["id"] for m in result["sources"][0]["metrics"]}


async def test_a_service_user_without_mcp_use_is_refused(db) -> None:
    await make_user(db, SERVICE_EMAIL, role="viewer", kind="service")
    assert await server.run_tool("list_metrics", {}) == server.NO_MCP_ACCESS

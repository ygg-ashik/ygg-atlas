"""MCP until phase 4: a shared token that is required, and a service user's grants."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from structlog.testing import capture_logs

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


async def test_the_bearer_scheme_is_case_insensitive(
    mcp_token: Callable[[str], None],
) -> None:
    mcp_token("s3cret")
    assert (await _get({"Authorization": "bearer s3cret"})).status_code == 200
    assert (await _get({"Authorization": "BEARER s3cret"})).status_code == 200


@pytest.mark.parametrize(
    "header",
    [None, "", "Basic s3cret", "s3cret", "Bearer ", "Bearer", "Bearers3cret"],
)
async def test_malformed_authorization_is_unauthorized(
    mcp_token: Callable[[str], None], header: str | None
) -> None:
    mcp_token("s3cret")
    headers = {} if header is None else {"Authorization": header}
    assert (await _get(headers)).status_code == 401


def test_standalone_mode_serves_the_token_gated_app_on_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(
        server.uvicorn, "run", lambda app, **kw: calls.append((app, kw))
    )
    server.serve_standalone()
    [(app, kwargs)] = calls
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8090
    assert any(m.cls is server.BearerTokenMiddleware for m in app.user_middleware)


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


async def test_a_disabled_service_user_is_not_ready(db) -> None:
    await make_user(
        db, SERVICE_EMAIL, role="analyst", kind="service", status="disabled"
    )
    with capture_logs() as logs:
        assert await server.run_tool("list_metrics", {}) == server.NOT_READY
    assert any(e["event"] == "mcp.service_user_unavailable" for e in logs)


async def test_a_human_holding_the_service_email_is_not_ready(db) -> None:
    await make_user(db, SERVICE_EMAIL, role="analyst", kind="human")
    with capture_logs() as logs:
        assert await server.run_tool("list_metrics", {}) == server.NOT_READY
    assert any(e["event"] == "mcp.service_user_unavailable" for e in logs)


async def test_a_failing_service_lookup_is_unavailable_and_leaks_nothing(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("OperationalError: connection to 10.0.0.5 refused")

    monkeypatch.setattr(server, "service_principal", boom)
    with capture_logs() as logs:
        result = await server.run_tool("list_metrics", {})
    assert result == server.UNAVAILABLE
    assert "10.0.0.5" not in str(result)
    assert any(e["event"] == "mcp.access_check_failed" for e in logs)


async def test_a_failing_policy_lookup_is_unavailable(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    await make_user(db, SERVICE_EMAIL, role="analyst", kind="service")

    async def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("db exploded")

    monkeypatch.setattr(server, "policy_for", boom)
    result = await server.run_tool("list_metrics", {})
    assert result == server.UNAVAILABLE

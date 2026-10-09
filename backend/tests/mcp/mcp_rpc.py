"""The whole MCP surface over HTTP, as main.py wires it (Task 6).

`full_app` mounts a fresh `build_mcp` server (C9) with every router the real app
has; tests wrap requests in `async with server.session_manager.run():`. `rpc` speaks
streamable HTTP: one JSON-RPC POST, the answer read from the SSE `data:` line.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI

from app.access import AccessError, access_error_handler
from app.config import Settings, get_settings
from app.mcp import AtlasMCP, build_http_app, build_mcp, discovery_router, mcp_router

BASE = "http://localhost:8080"
MCP_PATH = "/mcp-server/mcp"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def full_app(settings: Settings | None = None) -> tuple[FastAPI, AtlasMCP]:
    resolved = settings or get_settings()
    server = build_mcp(resolved)
    app = FastAPI()
    app.add_exception_handler(AccessError, access_error_handler)
    app.include_router(mcp_router)
    app.include_router(discovery_router)
    app.mount("/mcp-server", build_http_app(server, resolved))
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    return app, server


LOOPBACK_PEER = "127.0.0.1"  # what httpx's ASGI transport reports by default


@asynccontextmanager
async def serving(
    settings: Settings | None = None, *, peer: str = LOOPBACK_PEER
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    """A fresh app and its running session manager, with an HTTP client on it that
    connects from `peer` (loopback by default, which per-source limits key as
    "unknown")."""
    app, server = full_app(settings)
    transport = httpx.ASGITransport(app=app, client=(peer, 123))
    async with (
        server.session_manager.run(),
        httpx.AsyncClient(transport=transport, base_url=BASE) as client,
    ):
        yield app, client


async def post_rpc(
    client: httpx.AsyncClient,
    token: str | None,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    sent = dict(MCP_HEADERS) | (headers or {})
    if token is not None:
        sent["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return await client.post(MCP_PATH, json=body, headers=sent)


def rpc_result(response: httpx.Response) -> dict[str, Any]:
    """The JSON-RPC `result` from an SSE (or JSON) answer."""
    assert response.status_code == 200, response.text
    text = response.text
    if response.headers["content-type"].startswith("text/event-stream"):
        data = [
            line[5:].strip() for line in text.splitlines() if line.startswith("data:")
        ]
        assert data, text
        text = data[-1]
    message: dict[str, Any] = json.loads(text)
    assert "error" not in message, message
    result: dict[str, Any] = message["result"]
    return result


async def rpc(
    client: httpx.AsyncClient,
    token: str,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return rpc_result(await post_rpc(client, token, method, params))


INITIALIZE = {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "atlas-tests", "version": "1"},
}


async def tool_names(client: httpx.AsyncClient, token: str) -> set[str]:
    result = await rpc(client, token, "tools/list")
    return {tool["name"] for tool in result["tools"]}


async def call_tool(
    client: httpx.AsyncClient,
    token: str,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The tool's JSON result (FastMCP sends it as one text content block)."""
    result = await rpc(
        client, token, "tools/call", {"name": name, "arguments": arguments or {}}
    )
    assert not result.get("isError"), result
    (content,) = result["content"]
    parsed: dict[str, Any] = json.loads(content["text"])
    return parsed

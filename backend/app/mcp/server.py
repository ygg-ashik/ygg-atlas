"""MCP server exposing the atlas tools to external MCP clients.

Same implementations as the chat agent (app.atlas.tools) — no drift between
surfaces. Auth until phase 4: the shared ATLAS_MCP_TOKEN is required (no token =
MCP off), and every call runs as the MCP service user (MCP_SERVICE_EMAIL) under
that user's grants.

Run standalone:  uv run python -m app.mcp.server        (streamable HTTP :8090/mcp)
"""

import hmac
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.access import MCP_USE, PolicyUnavailableError, policy_for
from app.atlas import AtlasCaller, AtlasTools
from app.config import get_settings
from app.database import get_session_factory
from app.identity import service_principal

mcp = FastMCP("ygg-atlas", stateless_http=True)


NOT_READY = {"error": "MCP isn't set up on this server yet. Ask an atlas admin."}
NO_MCP_ACCESS = {"error": "This MCP connection's account doesn't include MCP access."}
UNAVAILABLE = {"error": "The access check is unavailable right now. Try again shortly."}


async def run_tool(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one atlas tool as the MCP service user, under its policy (fail closed)."""
    async with get_session_factory()() as db:
        principal = await service_principal(db, get_settings().mcp_service_email)
        if principal is None:
            return dict(NOT_READY)
        try:
            policy = await policy_for(db, principal)
        except PolicyUnavailableError:
            return dict(UNAVAILABLE)
        if not policy.has(MCP_USE):
            return dict(NO_MCP_ACCESS)
        caller = AtlasCaller(
            user_id=principal.user_id,
            auth_method=principal.auth_method,
            surface="mcp",
        )
        return await AtlasTools(caller, policy, db=db).execute(tool, arguments)


@mcp.tool()
async def list_metrics() -> dict:
    """List every governed metric and funnel in the atlas, with descriptions."""
    return await run_tool("list_metrics", {})


# Descriptions too long for one docstring line are passed explicitly: FastMCP
# publishes a docstring verbatim, so wrapping it would change the description.
@mcp.tool(
    description="Get a governed metric value. Range metrics need ISO dates; "
    "snapshot metrics don't."
)
async def query_metric(
    metric_id: str, start_date: str | None = None, end_date: str | None = None
) -> dict:
    return await run_tool(
        "query_metric",
        {"metric_id": metric_id, "start_date": start_date, "end_date": end_date},
    )


@mcp.tool()
async def metric_breakdown(
    metric_id: str,
    limit: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Top-N breakdown of a metric (e.g. top accounts by revenue, tasks per CSM)."""
    return await run_tool(
        "metric_breakdown",
        {
            "metric_id": metric_id,
            "limit": limit,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@mcp.tool()
async def describe_entity(entity_id: str) -> dict:
    """Describe an atlas entity: fields, PII flags, its metrics and funnels."""
    return await run_tool("describe_entity", {"entity_id": entity_id})


@mcp.tool(
    description="Analyze a governed funnel over a date range: step conversion and "
    "biggest drop-off."
)
async def funnel_analyze(funnel_id: str, start_date: str, end_date: str) -> dict:
    return await run_tool(
        "funnel_analyze",
        {"funnel_id": funnel_id, "start_date": start_date, "end_date": end_date},
    )


@mcp.tool()
async def compare_periods(
    metric_id: str,
    period_a_start: str,
    period_a_end: str,
    period_b_start: str,
    period_b_end: str,
) -> dict:
    """Compare a metric between two date ranges: values, delta, percent change."""
    return await run_tool(
        "compare_periods",
        {
            "metric_id": metric_id,
            "period_a_start": period_a_start,
            "period_a_end": period_a_end,
            "period_b_start": period_b_start,
            "period_b_end": period_b_end,
        },
    )


@mcp.tool()
async def search_atlas(query: str) -> dict:
    """Keyword-search the atlas for entities, metrics, and funnels matching a topic."""
    return await run_tool("search_atlas", {"query": query})


class BearerTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        expected = get_settings().atlas_mcp_token
        if not expected:
            return JSONResponse(
                {"error": "MCP is off on this server (ATLAS_MCP_TOKEN is not set)."},
                status_code=503,
            )
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied.encode(), f"Bearer {expected}".encode()):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def build_http_app() -> Starlette:
    """Streamable-HTTP ASGI app with bearer-token middleware, mountable in FastAPI."""
    app = mcp.streamable_http_app()
    app.user_middleware.insert(0, Middleware(BearerTokenMiddleware))
    app.middleware_stack = app.build_middleware_stack()
    return app


if __name__ == "__main__":
    mcp.settings.port = 8090
    mcp.run(transport="streamable-http")

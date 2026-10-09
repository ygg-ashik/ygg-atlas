"""The MCP server: the atlas tools, served per principal (D19, D20, D26, D27).

Same implementations as the chat agent (`app.atlas.tools`), so the surfaces never
drift. Every request carries a bearer that identity's door resolves to one person or
service account (`AtlasTokenVerifier`); `tools/list` shows only what that principal
may use and every `tools/call` runs, and is audited, as them with the credential's
ids. Any failure collapses to an empty list or the "unavailable" result (fail
closed). A caller without `mcp:use` gets no tools and a tool-level denial, never an
HTTP 403 (C7: a 403 would send MCP clients into a scope step-up loop).

The server is built by factories, not at import (C9): `build_mcp(settings)` and
`build_http_app(server, settings)`. main.py builds one; tests build one per test.

Run standalone:  uv run python -m app.mcp.server
    Serves the same bearer-protected app on 127.0.0.1:8090/mcp via uvicorn.
"""

from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType
from typing import Any, Final, Literal
from urllib.parse import urlsplit

import structlog
import uvicorn
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool as MCPTool
from pydantic import AnyHttpUrl
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.types import Scope

from app.access import MCP_USE, policy_for
from app.atlas import AtlasCaller, AtlasTools
from app.config import Settings, get_settings
from app.database import get_session_factory
from app.identity import OAuthConfig, OAuthService
from app.mcp.auth import (
    AtlasAccessToken,
    AtlasTokenVerifier,
    BearerRejectionScope,
    bearer_unrecognised,
)
from app.mcp.oauth_provider import AtlasOAuthProvider
from app.mcp.oauth_routes import build_oauth_routes
from app.mcp.ratelimit import (
    BEARER_FAILURES,
    MCP_CALLS,
    FailedBearerGuard,
    PrincipalRateLimit,
)

logger = structlog.get_logger()

ToolNeed = Literal["mcp", "metrics", "funnels"]
# What each tool needs beyond mcp:use to be listed (spec §6 point 1). A registered
# tool missing from this table is never listed.
TOOL_REQUIREMENTS: Final[Mapping[str, ToolNeed]] = MappingProxyType(
    {
        "list_metrics": "mcp",
        "search_atlas": "mcp",
        "describe_entity": "mcp",
        "query_metric": "metrics",
        "metric_breakdown": "metrics",
        "compare_periods": "metrics",
        "funnel_analyze": "funnels",
    }
)

NO_MCP_ACCESS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "error": "This account doesn't include MCP access (mcp:use). "
        "Ask an atlas admin, or request access in atlas."
    }
)
UNAVAILABLE: Final[Mapping[str, str]] = MappingProxyType(
    {"error": "Atlas is unavailable right now. Try again shortly."}
)

SERVER_NAME: Final = "ygg-atlas"
STANDALONE_HOST: Final = "127.0.0.1"
STANDALONE_PORT: Final = 8090


# ---- the per-principal tool surface -------------------------------------------------


def _caller_token() -> AtlasAccessToken | None:
    """The request's token, set by the SDK's AuthContextMiddleware (a contextvar the
    stateless transport's server task inherits from the request task)."""
    token = get_access_token()
    return token if isinstance(token, AtlasAccessToken) else None


def _caller(token: AtlasAccessToken) -> AtlasCaller:
    principal = token.principal
    return AtlasCaller(
        user_id=principal.user_id,
        auth_method=principal.auth_method,
        surface="mcp",
        token_id=principal.token_id,
        client_id=principal.client_id,
    )


async def run_tool(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """One atlas tool as the calling principal (D20). Every failure is "unavailable";
    nothing internal reaches the client (FastMCP would forward an error verbatim)."""
    token = _caller_token()
    if token is None:  # cannot happen behind RequireAuthMiddleware
        logger.error("mcp.no_principal", tool=tool)
        return dict(UNAVAILABLE)
    try:
        async with get_session_factory()() as db:
            policy = await policy_for(db, token.principal)
            if not policy.has(MCP_USE):
                logger.info(
                    "mcp.tool_denied",
                    tool=tool,
                    user_id=str(token.principal.user_id),
                    token_id=str(token.token_id),
                    client_id=token.principal.client_id,
                )
                return dict(NO_MCP_ACCESS)
            return await AtlasTools(_caller(token), policy, db=db).execute(
                tool, arguments
            )
    except Exception as exc:  # PolicyUnavailableError included: fail closed
        # Not logger.exception: no traceback (its frames could hold request data).
        logger.error("mcp.tool_unavailable", tool=tool, error=type(exc).__name__)
        return dict(UNAVAILABLE)


async def _allowed_tool_names() -> frozenset[str]:
    """The tools the caller may see; empty without a principal, without mcp:use, or
    on any failure."""
    token = _caller_token()
    if token is None:
        return frozenset()
    try:
        async with get_session_factory()() as db:
            policy = await policy_for(db, token.principal)
        if not policy.has(MCP_USE):
            return frozenset()
        atlas = AtlasTools(_caller(token), policy, db=None)
        visible: set[ToolNeed] = {"mcp"}
        if atlas.visible_metrics():
            visible.add("metrics")
        if atlas.visible_funnels():
            visible.add("funnels")
    except Exception as exc:
        logger.error("mcp.list_tools_failed", error=type(exc).__name__)
        return frozenset()
    return frozenset(
        name for name, need in TOOL_REQUIREMENTS.items() if need in visible
    )


class AtlasMCP(FastMCP[object]):
    """FastMCP whose `tools/list` is filtered per principal (spec §6 point 1)."""

    def __init__(self, verifier: AtlasTokenVerifier, settings: Settings) -> None:
        super().__init__(
            SERVER_NAME,
            token_verifier=verifier,
            auth=AuthSettings(
                issuer_url=AnyHttpUrl(settings.mcp_issuer_url),
                resource_server_url=AnyHttpUrl(settings.mcp_resource_url),
                validate_token_resource=True,  # audience enforced per request (D7)
            ),
            stateless_http=True,
            transport_security=transport_security_for(settings.atlas_public_url),
        )
        self.atlas_verifier: Final = verifier

    async def list_tools(self) -> list[MCPTool]:
        """FastMCP._setup_handlers registers the bound `self.list_tools`, so this
        override is what `tools/list` calls."""
        tools = await super().list_tools()
        allowed = await _allowed_tool_names()
        return [tool for tool in tools if tool.name in allowed]


# ---- tools: names, signatures and descriptions are the published contract -----------


async def list_metrics() -> dict[str, Any]:
    return await run_tool("list_metrics", {})


async def query_metric(
    metric_id: str, start_date: str | None = None, end_date: str | None = None
) -> dict[str, Any]:
    return await run_tool(
        "query_metric",
        {"metric_id": metric_id, "start_date": start_date, "end_date": end_date},
    )


async def metric_breakdown(
    metric_id: str,
    limit: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    return await run_tool(
        "metric_breakdown",
        {
            "metric_id": metric_id,
            "limit": limit,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


async def describe_entity(entity_id: str) -> dict[str, Any]:
    return await run_tool("describe_entity", {"entity_id": entity_id})


async def funnel_analyze(
    funnel_id: str, start_date: str, end_date: str
) -> dict[str, Any]:
    return await run_tool(
        "funnel_analyze",
        {"funnel_id": funnel_id, "start_date": start_date, "end_date": end_date},
    )


async def compare_periods(
    metric_id: str,
    period_a_start: str,
    period_a_end: str,
    period_b_start: str,
    period_b_end: str,
) -> dict[str, Any]:
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


async def search_atlas(query: str) -> dict[str, Any]:
    return await run_tool("search_atlas", {"query": query})


ToolFn = Callable[..., Awaitable[dict[str, Any]]]

_TOOLS: Final[tuple[tuple[ToolFn, str], ...]] = (
    (
        list_metrics,
        "List every governed metric and funnel in the atlas, with descriptions.",
    ),
    (
        query_metric,
        "Get a governed metric value. Range metrics need ISO dates; "
        "snapshot metrics don't.",
    ),
    (
        metric_breakdown,
        "Top-N breakdown of a metric (e.g. top accounts by revenue, tasks per CSM).",
    ),
    (
        describe_entity,
        "Describe an atlas entity: fields, PII flags, its metrics and funnels.",
    ),
    (
        funnel_analyze,
        "Analyze a governed funnel over a date range: step conversion and "
        "biggest drop-off.",
    ),
    (
        compare_periods,
        "Compare a metric between two date ranges: values, delta, percent change.",
    ),
    (
        search_atlas,
        "Keyword-search the atlas for entities, metrics, and funnels matching a topic.",
    ),
)


def _register_tools(server: AtlasMCP) -> None:
    # Unstructured, as before: results stay JSON text, with no output schema.
    for fn, description in _TOOLS:
        server.add_tool(
            fn, name=fn.__name__, description=description, structured_output=False
        )


# ---- factories ---------------------------------------------------------------------


def transport_security_for(public_url: str) -> TransportSecuritySettings:
    """D26 / C1: DNS-rebinding protection stays on, but our own public host is
    allowed with and without its port (nginx's `$host` drops it), plus loopback."""
    parts = urlsplit(public_url)
    host, netloc = parts.hostname or "localhost", parts.netloc
    hosts = {
        netloc,
        host,
        "localhost",
        "127.0.0.1",
        "localhost:*",
        "127.0.0.1:*",
        "[::1]:*",
    }
    origins = {
        f"{parts.scheme}://{netloc}",
        "http://localhost:*",
        "http://127.0.0.1:*",
        "http://[::1]:*",
    }
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(hosts),
        allowed_origins=sorted(origins),
    )


def build_mcp(settings: Settings) -> AtlasMCP:
    server = AtlasMCP(AtlasTokenVerifier(settings.mcp_resource_url), settings)
    _register_tools(server)
    return server


def _token_key(scope: Scope) -> str | None:
    """The per-token call budget's key (D16); None (skip) when unauthenticated."""
    user = scope.get("user")
    if isinstance(user, AuthenticatedUser):
        token = user.access_token
        if isinstance(token, AtlasAccessToken):
            return str(token.token_id)
    return None


def build_http_app(server: AtlasMCP, settings: Settings) -> Starlette:
    """The `/mcp-server` sub-app: `/mcp` behind the SDK's bearer middleware (401 with
    `WWW-Authenticate: Bearer ... resource_metadata="<PRM URL>"`), plus our OAuth
    routes.

    Middleware, outermost first: the failed-bearer guard (E1: counts only bearers
    the door does not recognise, read from the verdict `BearerRejectionScope` bounds
    to this request), the SDK's authentication and auth-context middleware, then the
    per-token call budget. All pure ASGI, so they run in the request's own task."""
    config = OAuthConfig.from_settings(settings)
    provider = AtlasOAuthProvider(config, server.atlas_verifier)
    app = server.streamable_http_app()
    app.router.routes.extend(build_oauth_routes(provider, config))
    app.user_middleware.insert(0, Middleware(BearerRejectionScope))
    app.user_middleware.insert(
        0,
        Middleware(
            FailedBearerGuard, policy=BEARER_FAILURES, counts=bearer_unrecognised
        ),
    )
    app.user_middleware.append(
        Middleware(PrincipalRateLimit, policy=MCP_CALLS, key=_token_key)
    )
    app.middleware_stack = app.build_middleware_stack()
    return app


async def prepare_mcp_auth(db: AsyncSession, settings: Settings) -> None:
    """Startup: report the advertised URLs and collect stale credentials. Never
    raises: MCP auth trouble must not keep the chat API down."""
    logger.info(
        "mcp.auth_ready",
        issuer=settings.mcp_issuer_url,
        resource=settings.mcp_resource_url,
        hosted_connectors=settings.hosted_connectors_enabled,
    )
    if settings.environment == "production" and not settings.hosted_connectors_enabled:
        logger.warning("mcp.public_url_local", public_url=settings.atlas_public_url)
    try:
        await OAuthService(db, OAuthConfig.from_settings(settings)).gc()
    except Exception as exc:
        await db.rollback()
        logger.error("mcp.credentials_gc_failed", error=type(exc).__name__)


def serve_standalone() -> None:
    """Serve the bearer-protected app alone (its lifespan runs the session manager)."""
    settings = get_settings()
    uvicorn.run(
        build_http_app(build_mcp(settings), settings),
        host=STANDALONE_HOST,
        port=STANDALONE_PORT,
    )


if __name__ == "__main__":
    serve_standalone()

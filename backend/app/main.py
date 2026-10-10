from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Final

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app.access import (
    AccessError,
    access_error_handler,
    access_router,
    prepare_access,
    sync_scope_dimensions,
)
from app.api import chat_router
from app.atlas import get_registry
from app.config import get_settings
from app.database import get_session_factory
from app.identity import identity_router
from app.insights import router as insights_router
from app.mcp import (
    AtlasMCP,
    build_http_app,
    build_mcp,
    discovery_router,
    install_access_log_redaction,
    mcp_router,
    prepare_mcp_auth,
)

logger = structlog.get_logger()

install_access_log_redaction()

_mcp: AtlasMCP | None
try:
    _mcp = build_mcp(get_settings())
    _mcp_app = build_http_app(_mcp, get_settings())
except Exception as exc:  # MCP is optional at runtime; never block the chat API
    logger.error("mcp.load_failed", error=type(exc).__name__)
    _mcp = None
    _mcp_app = None


async def apply_startup() -> None:
    settings = get_settings()
    async with get_session_factory()() as db:
        # Before prepare_access: its version bump invalidates any policy
        # evaluated against the old scope-dimension mirror (C8).
        await sync_scope_dimensions(db, get_registry().scope_catalog())
        # Bootstrap admins are created by access: a role is an authorization
        # change, audited and versioned in the same commit (spec §3.3).
        await prepare_access(db, settings.bootstrap_admin_list)
        await prepare_mcp_auth(db, settings)
    if (
        settings.environment == "production"
        and not settings.atlas_pseudonym_key.strip()
    ):
        # Not fatal: pseudonymised labels degrade to suppressed (C13).
        logger.error("atlas.pseudonym_key_missing")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Schema is owned by Alembic: `alembic upgrade head` runs before the app starts.
    await apply_startup()
    logger.info("startup.complete")
    if _mcp is not None:
        # The mounted streamable-HTTP app requires its session manager running.
        async with _mcp.session_manager.run():
            yield
    else:
        yield


# Paths that answer CORS themselves: the MCP sub-app (the SDK and our OAuth routes,
# open to any origin like the SDK's own) and the root OAuth discovery documents.
# The SPA's allowlist with credentials applies to everything else.
_OWN_CORS_PREFIXES: Final = ("/mcp-server/", "/.well-known/oauth-")


class _ScopedCORS:
    """Pure ASGI: the global CORS middleware, except on paths with their own CORS
    (otherwise it refuses their preflights from origins outside CORS_ORIGINS)."""

    def __init__(self, app: ASGIApp, *, allow_origins: Sequence[str]) -> None:
        self._plain = app
        self._cors = CORSMiddleware(
            app,
            allow_origins=allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "") if scope["type"] == "http" else ""
        inner = self._plain if path.startswith(_OWN_CORS_PREFIXES) else self._cors
        await inner(scope, receive, send)


app = FastAPI(title="ygg-atlas", version="0.1.0", lifespan=lifespan)

app.add_middleware(_ScopedCORS, allow_origins=get_settings().cors_origin_list)
app.add_exception_handler(AccessError, access_error_handler)

app.include_router(chat_router)
app.include_router(identity_router)
app.include_router(access_router)
app.include_router(insights_router)
app.include_router(mcp_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


if _mcp_app is not None:
    # Discovery only when there is an MCP server to discover.
    app.include_router(discovery_router)
    app.mount("/mcp-server", _mcp_app)

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat_router
from app.config import get_settings
from app.database import get_session_factory
from app.identity import bootstrap_admins, identity_router
from app.insights import router as insights_router

logger = structlog.get_logger()

try:
    from app.mcp.server import build_http_app, mcp

    _mcp_app = build_http_app()
except Exception:  # MCP is optional at runtime; never block the chat API
    logger.exception("mcp.load_failed")
    mcp = None
    _mcp_app = None


async def apply_bootstrap_admins() -> None:
    async with get_session_factory()() as db:
        await bootstrap_admins(db, get_settings().bootstrap_admin_list)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Schema is owned by Alembic: `alembic upgrade head` runs before the app starts.
    await apply_bootstrap_admins()
    logger.info("startup.complete")
    if mcp is not None:
        # The mounted streamable-HTTP app requires its session manager running.
        async with mcp.session_manager.run():
            yield
    else:
        yield


app = FastAPI(title="ygg-atlas", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(identity_router)
app.include_router(insights_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


if _mcp_app is not None:
    app.mount("/mcp-server", _mcp_app)

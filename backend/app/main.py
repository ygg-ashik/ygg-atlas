from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel

from app.api import chat_router
from app.config import get_settings
from app.database import get_engine

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # MVP schema management; Alembic takes over once the schema stabilizes.
    async with get_engine().begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("startup.complete")
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


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


def _mount_mcp() -> None:
    try:
        from app.mcp.server import build_http_app

        app.mount("/mcp-server", build_http_app())
    except Exception:
        logger.exception("mcp.mount_failed")


_mount_mcp()

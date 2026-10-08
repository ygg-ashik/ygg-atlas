from collections.abc import AsyncGenerator
from functools import cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


@cache
def get_engine() -> AsyncEngine:
    """Process-wide engine for the ygg-atlas DB. Reset with `reset_database()`."""
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session


async def reset_database() -> None:
    """Test helper: dispose the cached engine, then drop it and its session factory."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()

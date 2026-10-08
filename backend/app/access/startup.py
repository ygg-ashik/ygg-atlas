"""Startup for access: mirror the capability catalog and invalidate cached policies."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.cache import shared_cache
from app.access.catalog import CAPABILITIES
from app.access.repository import AccessRepository


async def prepare_access(db: AsyncSession) -> None:
    repo = AccessRepository(db)
    await repo.ensure_policy_state()
    await repo.sync_capabilities(CAPABILITIES)
    # Bootstrap may have changed roles; a bump makes every worker re-evaluate.
    await repo.bump_version()
    await repo.commit()
    shared_cache().clear()

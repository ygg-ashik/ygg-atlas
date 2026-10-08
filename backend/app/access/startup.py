"""Startup for access: mirror the capability catalog and invalidate cached policies."""

from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.cache import shared_cache
from app.access.catalog import CAPABILITIES
from app.access.repository import AccessRepository

# A fixed, arbitrary bigint identifying this lock across every process and release.
STARTUP_LOCK_KEY: Final = 7_402_311


async def prepare_access(db: AsyncSession) -> None:
    repo = AccessRepository(db)
    if db.get_bind().dialect.name == "postgresql":
        # Two processes starting together would otherwise both try to insert the
        # same capability rows and one loses with an IntegrityError. The lock is
        # transaction-scoped: it serializes concurrent starts and is released
        # automatically at commit. SQLite has no concurrent writers to race
        # (it serializes writes at the database level), so no lock is needed there.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": STARTUP_LOCK_KEY}
        )
    await repo.ensure_policy_state()
    await repo.sync_capabilities(CAPABILITIES)
    # Bump on every start: cheap, and any role change made by bootstrap becomes
    # visible to every worker.
    await repo.bump_version()
    await repo.commit()
    shared_cache().clear()

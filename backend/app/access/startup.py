"""Startup for access: mirror the capability catalog, create the bootstrap
admins, and invalidate cached policies."""

from collections.abc import Iterable
from typing import Final

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.cache import shared_cache
from app.access.catalog import CAPABILITIES
from app.access.models import RbacChange
from app.access.repository import AccessRepository
from app.identity import User, UserKind

logger = structlog.get_logger()

# A fixed, arbitrary bigint identifying this lock across every process and release.
STARTUP_LOCK_KEY: Final = 7_402_311
ADMIN_ROLE: Final = "admin"
VIA_BOOTSTRAP: Final = "bootstrap"


async def prepare_access(
    db: AsyncSession, bootstrap_admins: Iterable[str] = ()
) -> None:
    """One transaction: catalog sync, bootstrap admins, version bump."""
    repo = AccessRepository(db)
    if db.get_bind().dialect.name == "postgresql":
        # Two processes starting together would otherwise both try to insert the
        # same capability rows (or bootstrap admins) and one loses with an
        # IntegrityError. The lock is transaction-scoped: it serializes
        # concurrent starts and is released automatically at commit. SQLite has
        # no concurrent writers to race (it serializes writes at the database
        # level), so no lock is needed there.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": STARTUP_LOCK_KEY}
        )
    await repo.ensure_policy_state()
    await repo.sync_capabilities(CAPABILITIES)
    await _bootstrap_admins(repo, bootstrap_admins)
    # Bump on every start: cheap, and it commits together with any bootstrap
    # admin it created, so every worker sees the change.
    await repo.bump_version()
    await repo.commit()
    shared_cache().clear()


async def _bootstrap_admins(repo: AccessRepository, emails: Iterable[str]) -> None:
    """Create each missing BOOTSTRAP_ADMINS user as an admin, audited (spec §3.3).

    An existing user's role is never changed: a demoted admin stays demoted
    across restarts, and a service identity is never elevated. Promote an
    existing user with the audited CLI (`set-role`) instead.
    """
    for email in emails:
        user = await repo.user_by_email(email)
        if user is None:
            user = User(email=email.strip().lower(), role=ADMIN_ROLE)
            if await repo.insert_user_if_absent(user):
                repo.add(_bootstrap_change(user))
                logger.info("identity.bootstrap_admin_created", user_id=str(user.id))
                continue
            # A concurrent sign-in created this email first: judge that row.
            user = await repo.user_by_email(email)
            if user is None:
                # The conflict was on something other than the email: skip,
                # never fail startup over it.
                logger.error("identity.bootstrap_admin_failed", email=email)
                continue
        if user.role != ADMIN_ROLE or user.kind == UserKind.SERVICE:
            logger.warning(
                "identity.bootstrap_admin_skipped",
                user_id=str(user.id),
                role=user.role,
                kind=str(user.kind),
            )


def _bootstrap_change(user: User) -> RbacChange:
    return RbacChange(
        actor_user_id=None,
        via=VIA_BOOTSTRAP,
        tenant=user.tenant,
        action="user.bootstrap_admin",
        object_type="user",
        object_id=str(user.id),
        before=None,
        after={"email": user.email, "role": ADMIN_ROLE},
    )

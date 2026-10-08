"""Startup bootstrap: the only way to create the first admins (spec §3.3)."""

from collections.abc import Iterable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User
from app.identity.repository import UserRepository

logger = structlog.get_logger()

ADMIN_ROLE = "admin"


async def bootstrap_admins(db: AsyncSession, emails: Iterable[str]) -> int:
    """Create or upgrade each email to admin. Returns how many rows changed."""
    users = UserRepository(db)
    changed = 0
    for email in emails:
        user = await users.get_by_email(email)
        if user is None:
            await users.save(User(email=email, role=ADMIN_ROLE))
            changed += 1
        elif user.role != ADMIN_ROLE:
            user.role = ADMIN_ROLE
            await users.save(user)
            changed += 1
    if changed:
        logger.info("identity.bootstrap_admins", changed=changed)
    return changed

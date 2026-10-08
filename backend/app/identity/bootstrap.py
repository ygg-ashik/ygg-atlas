"""Startup bootstrap: the only way to create the first admins (spec §3.3)."""

from collections.abc import Iterable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User, UserKind
from app.identity.repository import UserRepository

logger = structlog.get_logger()

ADMIN_ROLE = "admin"


async def bootstrap_admins(db: AsyncSession, emails: Iterable[str]) -> int:
    """Create or upgrade each email to admin. Returns how many rows changed.

    An email that already belongs to a service identity is skipped: service
    users are authorized by their own grants, never by role elevation.
    """
    users = UserRepository(db)
    changed = 0
    for email in emails:
        user = await users.get_by_email(email)
        if user is not None and user.kind == UserKind.SERVICE:
            logger.warning(
                "identity.bootstrap_skips_service_user", user_id=str(user.id)
            )
            continue
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


async def ensure_service_user(
    db: AsyncSession, email: str, display_name: str, role: str
) -> User:
    """Create a service identity once. An existing row is returned unchanged."""
    users = UserRepository(db)
    user = await users.get_by_email(email)
    if user is None:
        user = await users.create_or_get(
            User(
                email=email,
                display_name=display_name,
                kind=UserKind.SERVICE,
                role=role,
            )
        )
        logger.info("identity.service_user_created", user_id=str(user.id))
    elif user.kind != UserKind.SERVICE:
        logger.warning("identity.service_email_taken", user_id=str(user.id))
    return user

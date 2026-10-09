"""Startup bootstrap for identity: the service identities.

Bootstrap admins are created by `app.access.prepare_access`: a role is an
authorization change, audited and versioned with it (spec §3.3).
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User, UserKind
from app.identity.repository import UserRepository

logger = structlog.get_logger()


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

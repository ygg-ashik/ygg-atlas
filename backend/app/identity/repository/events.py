"""Database access for credential_events (the credential audit trail)."""

from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.identity.models import CredentialEvent, User


class EventRepository:
    """Reads credential events; services stage new ones with the change they record."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_events(
        self, *, tenant: str, user_id: UUID | None = None, limit: int = 100
    ) -> list[CredentialEvent]:
        """Newest first. Events about no user (client registration, GC) belong to no
        tenant and are listed with every tenant's events unless a user is given."""
        statement = select(CredentialEvent).outerjoin(
            User, col(User.id) == col(CredentialEvent.user_id)
        )
        if user_id is not None:
            statement = statement.where(
                col(CredentialEvent.user_id) == user_id, col(User.tenant) == tenant
            )
        else:
            statement = statement.where(
                or_(col(User.tenant) == tenant, col(CredentialEvent.user_id).is_(None))
            )
        statement = statement.order_by(col(CredentialEvent.at).desc()).limit(limit)
        return list((await self._db.execute(statement)).scalars().all())

"""Database access for oauth_clients rows."""

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.identity.models import OAuthClient
from app.identity.repository.statements import run_dml


class ClientRepository:
    """Registered OAuth clients. Writes are staged; the calling service commits."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def client(self, client_id: str) -> OAuthClient | None:
        return await self._db.get(OAuthClient, client_id)

    async def list_clients(self, limit: int = 200) -> list[OAuthClient]:
        result = await self._db.execute(
            select(OAuthClient)
            .order_by(col(OAuthClient.registered_at).desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def revoke_client(self, client_id: str, now: datetime) -> bool:
        return (
            await run_dml(
                self._db,
                update(OAuthClient)
                .where(
                    col(OAuthClient.client_id) == client_id,
                    col(OAuthClient.revoked_at).is_(None),
                )
                .values(revoked_at=now),
            )
            == 1
        )

    async def touch_client(self, client_id: str, now: datetime) -> None:
        await run_dml(
            self._db,
            update(OAuthClient)
            .where(col(OAuthClient.client_id) == client_id)
            .values(last_used_at=now),
        )

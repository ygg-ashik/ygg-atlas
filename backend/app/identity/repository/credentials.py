"""One session's credential tables, staged and committed together."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.identity.repository.clients import ClientRepository
from app.identity.repository.codes import CodeRepository
from app.identity.repository.events import EventRepository
from app.identity.repository.families import FamilyRepository
from app.identity.repository.gc import GcRepository
from app.identity.repository.tokens import TokenRepository


class CredentialRepository:
    """Credential rows, one table repository each, over one session. Reads return
    rows; writes are staged and the calling service commits once, so a change and
    its credential_events row land together.

    Every "only once" write is one conditional UPDATE whose rowcount decides: on
    PostgreSQL READ COMMITTED the loser's UPDATE waits for the winner's row lock,
    re-checks its WHERE clause and matches 0 rows.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self.tokens = TokenRepository(db)
        self.families = FamilyRepository(db)
        self.clients = ClientRepository(db)
        self.codes = CodeRepository(db)
        self.events = EventRepository(db)
        self.gc = GcRepository(db)

    def add(self, row: SQLModel) -> None:
        self._db.add(row)

    async def commit(self) -> None:
        await self._db.commit()

    async def rollback(self) -> None:
        await self._db.rollback()

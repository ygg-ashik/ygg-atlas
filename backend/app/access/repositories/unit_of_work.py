"""One session's access repositories and the staged-write controls.

Reads return plain facts or rows. Writes are staged (`add`, `delete`, and the
topic repositories' `bump_version`, `ensure_policy_state`, `sync_capabilities`,
`finish_request`, `replace_scope_dimensions`); the calling service `commit`s
once, so a change, its audit row and the version bump land together.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.access.repositories.audit import AuditRepository
from app.access.repositories.grants import GrantRepository
from app.access.repositories.groups import GroupRepository
from app.access.repositories.policy_state import PolicyStateRepository
from app.access.repositories.requests import RequestRepository
from app.access.repositories.row_field import RowFieldRepository
from app.access.repositories.users import UserRepository


class AccessRepository:
    """All database access for the access module, over one session, grouped
    by the tables each repository reads and writes."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self.state = PolicyStateRepository(db)
        self.groups = GroupRepository(db)
        self.grants = GrantRepository(db)
        self.users = UserRepository(db)
        self.requests = RequestRepository(db)
        self.row_field = RowFieldRepository(db)
        self.audit = AuditRepository(db)

    def add(self, row: SQLModel) -> None:
        self._db.add(row)

    async def delete(self, row: SQLModel) -> None:
        await self._db.delete(row)

    async def commit(self) -> None:
        await self._db.commit()

    async def rollback(self) -> None:
        await self._db.rollback()

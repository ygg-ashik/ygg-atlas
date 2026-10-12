"""Database access for the users table. No business decisions here."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.identity.models import User


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self, user_id: UUID, *, fresh: bool = False) -> User | None:
        """`fresh` re-reads the row even if this session already holds it."""
        return await self._db.get(User, user_id, populate_existing=fresh)

    async def lock_user(self, user_id: UUID) -> None:
        """Hold the user row (FOR SHARE) until this transaction ends.

        An issuing transaction takes it after the family lock, so a concurrent
        disable (an UPDATE of the row) waits until the new pair is committed, and
        its post-commit revoke-all then sees that pair; or the disable commits
        first and the issuer reads the user as disabled. PostgreSQL only, like
        lock_family: SQLite serialises writers already.
        """
        if self._db.get_bind().dialect.name != "postgresql":
            return
        await self._db.execute(
            select(col(User.id))
            .where(col(User.id) == user_id)
            .with_for_update(read=True)
        )

    async def get_by_email(self, email: str) -> User | None:
        result = await self._db.execute(
            select(User).where(col(User.email) == email.strip().lower())
        )
        return result.scalar_one_or_none()

    async def get_by_firebase_uid(self, firebase_uid: str) -> User | None:
        result = await self._db.execute(
            select(User).where(col(User.firebase_uid) == firebase_uid)
        )
        return result.scalar_one_or_none()

    async def save(self, user: User) -> User:
        user.email = user.email.strip().lower()
        self._db.add(user)
        await self._db.commit()
        await self._db.refresh(user)
        return user

    async def create_or_get(self, user: User) -> User:
        """Insert a new user; if a concurrent request inserted the same identity first,
        return that row instead (unique email / firebase_uid decide the winner).

        The insert runs in a SAVEPOINT, so a conflict never discards other pending
        work in the caller's session.
        """
        user.email = user.email.strip().lower()
        try:
            async with self._db.begin_nested():
                self._db.add(user)
        except IntegrityError:
            existing = None
            if user.firebase_uid:
                existing = await self.get_by_firebase_uid(user.firebase_uid)
            if existing is None:
                existing = await self.get_by_email(user.email)
            if existing is None:
                raise  # the conflict was on something other than identity
            # The winner's row is returned as-is; a differing firebase_uid is linked
            # by the caller's next sign-in (IdentityService._find_or_link).
            return existing
        await self._db.commit()
        await self._db.refresh(user)
        return user

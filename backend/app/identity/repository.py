"""All database access for users. No business decisions here."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.identity.models import User


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self, user_id: UUID) -> User | None:
        return await self._db.get(User, user_id)

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

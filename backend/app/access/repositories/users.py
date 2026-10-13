"""Users as the access module reads them: lookups, the user list, row locks."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.access.facts import UserFacts
from app.access.models import GroupMember
from app.access.repositories.filters import equal_where
from app.access.schemas import UserQuery
from app.identity import User, UserKind, UserStatus


class UserRepository:
    """The users the access module reads, locks and creates."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def user_facts(self, user_id: UUID) -> UserFacts | None:
        user = await self._db.get(User, user_id, populate_existing=True)
        if user is None:
            return None
        return UserFacts(user.id, user.role, user.status, user.tenant)

    async def user(self, user_id: UUID) -> User | None:
        return await self._db.get(User, user_id, populate_existing=True)

    async def user_by_email(self, email: str) -> User | None:
        """Look up a user by email, globally: `users.email` is unique across
        tenants, so this needs no tenant parameter. Used by the CLI, which has
        no tenant-scoped actor to look a user up through."""
        stmt = (
            select(User)
            .where(col(User.email) == email.strip().lower())
            .execution_options(populate_existing=True)
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def users_by_id(self, user_ids: Iterable[UUID]) -> dict[UUID, User]:
        ids = list(set(user_ids))
        if not ids:
            return {}
        stmt = (
            select(User)
            .where(col(User.id).in_(ids))
            .execution_options(populate_existing=True)
        )
        return {u.id: u for u in (await self._db.execute(stmt)).scalars().all()}

    async def list_users(
        self, tenant: str, query: UserQuery, after: tuple[str, UUID] | None = None
    ) -> list[User]:
        """Users of `tenant` by (email, id) ascending, filtered; returns up to
        `query.limit + 1` rows so the caller can tell whether a next page exists."""
        email, row_id = col(User.email), col(User.id)
        stmt = select(User).where(
            col(User.tenant) == tenant,
            *equal_where(
                (col(User.role), query.role),
                (col(User.status), query.status),
                (col(User.kind), query.kind),
            ),
        )
        search = query.q.strip()
        if search:
            stmt = stmt.where(_matches_user(search))
        if after is not None:
            last_email, last_id = after
            stmt = stmt.where(
                or_(email > last_email, and_(email == last_email, row_id > last_id))
            )
        stmt = (
            stmt.order_by(email, row_id)
            .limit(query.limit + 1)
            .execution_options(populate_existing=True)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def member_candidates(
        self,
        tenant: str,
        group_id: UUID,
        search: str,
        *,
        exclude_user_id: UUID | None,
        limit: int,
    ) -> list[User]:
        """Active human users of `tenant` matching `search` who are not yet
        direct members of `group_id`, by email."""
        already = (
            select(col(GroupMember.user_id))
            .where(col(GroupMember.group_id) == group_id)
            .scalar_subquery()
        )
        stmt = select(User).where(
            col(User.tenant) == tenant,
            col(User.status) == UserStatus.ACTIVE,
            col(User.kind) != UserKind.SERVICE,
            col(User.id).not_in(already),
            _matches_user(search),
        )
        if exclude_user_id is not None:
            stmt = stmt.where(col(User.id) != exclude_user_id)
        stmt = (
            stmt.order_by(col(User.email), col(User.id))
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def lock_user(self, user_id: UUID) -> User | None:
        """Read the user row `FOR UPDATE` (Postgres), serializing one user's
        request creates so the pending cap holds; a no-op on SQLite, which
        serializes writers anyway."""
        stmt = (
            select(User)
            .where(col(User.id) == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def insert_user_if_absent(self, user: User) -> bool:
        """Stage `user` in a SAVEPOINT; False (nothing staged) when a row with
        the same identity already exists, e.g. a concurrent sign-in won."""
        try:
            async with self._db.begin_nested():
                self._db.add(user)
        except IntegrityError:
            return False
        return True


def _matches_user(search: str) -> ColumnElement[bool]:
    """Case-insensitive substring match on email or display name; `%` and `_`
    are literal."""
    return or_(
        col(User.email).icontains(search, autoescape=True),
        col(User.display_name).icontains(search, autoescape=True),
    )

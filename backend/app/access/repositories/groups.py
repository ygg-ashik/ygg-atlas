"""Groups and group_members: the tenant's tree, memberships and managers."""

from collections.abc import Iterable, Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.access.facts import STANDING_MANAGER, SUBJECT_GROUP, GroupFacts
from app.access.models import Grant, Group, GroupMember
from app.identity import User, UserStatus


class GroupRepository:
    """Groups and their memberships."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def tenant_groups(self, tenant: str) -> dict[UUID, GroupFacts]:
        # populate_existing: another session may have changed this row after
        # ours loaded it into its identity map (expire_on_commit=False leaves
        # it stale); a bumped version must never still read it.
        rows = (
            (
                await self._db.execute(
                    select(Group)
                    .where(col(Group.tenant) == tenant)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        return {g.id: GroupFacts(g.id, g.name, g.parent_id, g.tenant) for g in rows}

    async def memberships(self, user_id: UUID) -> dict[UUID, str]:
        rows = (
            (
                await self._db.execute(
                    select(GroupMember)
                    .where(col(GroupMember.user_id) == user_id)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        return {m.group_id: m.standing for m in rows}

    async def group(self, group_id: UUID) -> Group | None:
        return await self._db.get(Group, group_id, populate_existing=True)

    async def group_by_name(self, tenant: str, name: str) -> Group | None:
        stmt = (
            select(Group)
            .where(col(Group.tenant) == tenant, col(Group.name) == name)
            .execution_options(populate_existing=True)
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_groups(self, tenant: str) -> list[Group]:
        stmt = (
            select(Group)
            .where(col(Group.tenant) == tenant)
            .order_by(col(Group.name))
            .execution_options(populate_existing=True)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def group_in_use(self, group_id: UUID) -> bool:
        """True when the group has subgroups, members or grants."""
        checks = (
            select(func.count())
            .select_from(Group)
            .where(col(Group.parent_id) == group_id),
            select(func.count())
            .select_from(GroupMember)
            .where(col(GroupMember.group_id) == group_id),
            select(func.count())
            .select_from(Grant)
            .where(
                col(Grant.subject_type) == SUBJECT_GROUP,
                col(Grant.subject_id) == group_id,
            ),
        )
        for stmt in checks:
            if (await self._db.execute(stmt)).scalar_one():
                return True
        return False

    async def member(self, group_id: UUID, user_id: UUID) -> GroupMember | None:
        return await self._db.get(
            GroupMember, (group_id, user_id), populate_existing=True
        )

    async def list_members(self, group_id: UUID) -> list[tuple[GroupMember, User]]:
        stmt = (
            select(GroupMember, User)
            .join(User, col(User.id) == col(GroupMember.user_id))
            .where(col(GroupMember.group_id) == group_id)
            .order_by(col(User.email))
            .execution_options(populate_existing=True)
        )
        # SQLModel's Select[tuple[_T0, _T1]] re-wraps _T in another tuple
        # (sql/_expression_select_cls.py), so the static row type from
        # .tuples() is one level deeper than the actual runtime rows.
        rows = cast(
            "Sequence[tuple[GroupMember, User]]",
            (await self._db.execute(stmt)).tuples().all(),
        )
        return list(rows)

    async def count_members(self, group_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(GroupMember)
            .where(col(GroupMember.group_id) == group_id)
        )
        return (await self._db.execute(stmt)).scalar_one()

    async def group_managers(self, group_ids: Iterable[UUID]) -> dict[UUID, list[str]]:
        """Active managers' display names per group (never emails), sorted;
        blank names are left out."""
        ids = list(group_ids)
        if not ids:
            return {}
        stmt = (
            select(col(GroupMember.group_id), col(User.display_name))
            .join(User, col(User.id) == col(GroupMember.user_id))
            .where(
                col(GroupMember.group_id).in_(ids),
                col(GroupMember.standing) == STANDING_MANAGER,
                col(User.status) == UserStatus.ACTIVE,
            )
            .order_by(col(User.display_name))
        )
        # Same SQLModel tuple typing quirk as list_members.
        rows = cast(
            "Sequence[tuple[UUID, str]]", (await self._db.execute(stmt)).tuples().all()
        )
        managers: dict[UUID, list[str]] = {}
        for group_id, name in rows:
            if name.strip():
                managers.setdefault(group_id, []).append(name)
        return managers

"""All database access for the access module.

Reads return plain facts or rows. Writes are staged (`add`, `delete`,
`bump_version`, `ensure_policy_state`, `sync_capabilities`); the calling
service `commit`s once, so a change, its audit row and the version bump
land together.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import ColumnElement, CursorResult, and_, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, col, select

from app.access.errors import PolicyUnavailableError
from app.access.facts import (
    SUBJECT_GROUP,
    SUBJECT_USER,
    GrantFacts,
    GroupFacts,
    UserFacts,
    as_utc,
)
from app.access.models import Capability, Grant, Group, GroupMember, PolicyState
from app.identity import User


class AccessRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ---- reads for the evaluator ---------------------------------------

    async def policy_version(self) -> int:
        version = (
            await self._db.execute(
                select(col(PolicyState.policy_version)).where(col(PolicyState.id) == 1)
            )
        ).scalar_one_or_none()
        if version is None:
            msg = "policy_state has no row"
            raise PolicyUnavailableError(msg)
        return version

    async def user_facts(self, user_id: UUID) -> UserFacts | None:
        user = await self._db.get(User, user_id, populate_existing=True)
        if user is None:
            return None
        return UserFacts(user.id, user.role, user.status, user.tenant)

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

    async def grants_for(
        self, user_id: UUID, group_ids: Iterable[UUID]
    ) -> list[GrantFacts]:
        ids = list(group_ids)
        clause: ColumnElement[bool] = and_(
            col(Grant.subject_type) == SUBJECT_USER, col(Grant.subject_id) == user_id
        )
        if ids:
            clause = or_(
                clause,
                and_(
                    col(Grant.subject_type) == SUBJECT_GROUP,
                    col(Grant.subject_id).in_(ids),
                ),
            )
        rows = (
            (
                await self._db.execute(
                    select(Grant)
                    .where(clause)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        return [
            GrantFacts(
                g.id,
                g.subject_type,
                g.subject_id,
                g.effect,
                g.target_kind,
                g.target,
                as_utc(g.expires_at),
            )
            for g in rows
        ]

    # ---- staged writes (the service commits) ----------------------------

    def add(self, row: SQLModel) -> None:
        self._db.add(row)

    async def delete(self, row: SQLModel) -> None:
        await self._db.delete(row)

    async def bump_version(self) -> None:
        # An UPDATE always executes through a cursor, so this is a CursorResult
        # (rowcount) at runtime; Session.execute only types it as the base Result.
        result = cast(
            "CursorResult[Any]",
            await self._db.execute(
                update(PolicyState)
                .where(col(PolicyState.id) == 1)
                .values(
                    policy_version=col(PolicyState.policy_version) + 1,
                    updated_at=datetime.now(UTC),
                )
            ),
        )
        if result.rowcount != 1:
            msg = "policy_state has no row"
            raise PolicyUnavailableError(msg)

    async def commit(self) -> None:
        await self._db.commit()

    async def rollback(self) -> None:
        await self._db.rollback()

    async def lock_for_write(self) -> None:
        """Serialize admin writes: take a row lock on policy_state (spec §9).

        On Postgres, `FOR UPDATE` blocks a concurrent writer until this
        transaction commits or rolls back, so two admin writes never race
        past each other's application-level checks (duplicate names,
        parent cycles, in-use deletes). SQLite's dialect silently drops
        `FOR UPDATE` at compile time, but aiosqlite serializes writers to
        one connection anyway, so the same call is a safe no-op there.
        """
        version = (
            await self._db.execute(
                select(col(PolicyState.policy_version))
                .where(col(PolicyState.id) == 1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if version is None:
            msg = "policy_state has no row"
            raise PolicyUnavailableError(msg)

    async def ensure_policy_state(self) -> None:
        if await self._db.get(PolicyState, 1, populate_existing=True) is None:
            self._db.add(PolicyState(id=1, policy_version=1))
            await self._db.flush()

    async def sync_capabilities(self, catalog: Mapping[str, str]) -> None:
        existing = {
            c.code: c
            for c in (
                await self._db.execute(
                    select(Capability).execution_options(populate_existing=True)
                )
            ).scalars()
        }
        for code, description in catalog.items():
            row = existing.get(code) or Capability(code=code, description=description)
            row.description = description
            row.deprecated = False
            self._db.add(row)
        for code, row in existing.items():
            if code not in catalog:
                row.deprecated = True
                self._db.add(row)

    # ---- reads for administration ---------------------------------------

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

    async def user(self, user_id: UUID) -> User | None:
        return await self._db.get(User, user_id, populate_existing=True)

    async def grant(self, grant_id: UUID) -> Grant | None:
        return await self._db.get(Grant, grant_id, populate_existing=True)

    async def list_grants(self, subject_type: str, subject_id: UUID) -> list[Grant]:
        stmt = (
            select(Grant)
            .where(
                col(Grant.subject_type) == subject_type,
                col(Grant.subject_id) == subject_id,
            )
            .order_by(col(Grant.created_at))
            .execution_options(populate_existing=True)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def find_grant(
        self, subject: tuple[str, UUID], effect: str, target_kind: str, target: str
    ) -> Grant | None:
        subject_type, subject_id = subject
        stmt = (
            select(Grant)
            .where(
                col(Grant.subject_type) == subject_type,
                col(Grant.subject_id) == subject_id,
                col(Grant.effect) == effect,
                col(Grant.target_kind) == target_kind,
                col(Grant.target) == target,
            )
            .execution_options(populate_existing=True)
        )
        return (await self._db.execute(stmt)).scalars().first()

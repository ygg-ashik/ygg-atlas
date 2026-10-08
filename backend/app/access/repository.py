"""All database access for the access module.

Reads return plain facts or rows. Writes are staged (`add`, `delete`,
`bump_version`, `ensure_policy_state`, `sync_capabilities`); the calling
service `commit`s once, so a change, its audit row and the version bump
land together.
"""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, col, select

from app.access.errors import PolicyUnavailableError
from app.access.facts import (
    SUBJECT_GROUP,
    SUBJECT_USER,
    GrantFacts,
    GroupFacts,
    UserFacts,
)
from app.access.models import Capability, Grant, Group, GroupMember, PolicyState
from app.identity import User


def _aware(moment: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; every stored timestamp is UTC (CLAUDE.md)."""
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=UTC)


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
                _aware(g.expires_at),
            )
            for g in rows
        ]

    # ---- staged writes (the service commits) ----------------------------

    def add(self, row: SQLModel) -> None:
        self._db.add(row)

    async def delete(self, row: SQLModel) -> None:
        await self._db.delete(row)

    async def bump_version(self) -> None:
        await self._db.execute(
            update(PolicyState)
            .where(col(PolicyState.id) == 1)
            .values(
                policy_version=col(PolicyState.policy_version) + 1,
                updated_at=datetime.now(UTC),
            )
        )

    async def commit(self) -> None:
        await self._db.commit()

    async def ensure_policy_state(self) -> None:
        if await self._db.get(PolicyState, 1, populate_existing=True) is None:
            self._db.add(PolicyState(id=1, policy_version=1))
            await self._db.flush()

    async def sync_capabilities(self, catalog: Mapping[str, str]) -> None:
        existing = {
            c.code: c for c in (await self._db.execute(select(Capability))).scalars()
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

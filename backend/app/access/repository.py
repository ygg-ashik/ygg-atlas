"""All database access for the access module.

Reads return plain facts or rows. Writes are staged (`add`, `delete`,
`bump_version`, `ensure_policy_state`, `sync_capabilities`); the calling
service `commit`s once, so a change, its audit row and the version bump
land together.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import ColumnElement, CursorResult, and_, false, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped
from sqlmodel import SQLModel, col, select

from app.access.errors import PolicyUnavailableError
from app.access.facts import (
    STANDING_MANAGER,
    SUBJECT_GROUP,
    SUBJECT_USER,
    GrantFacts,
    GroupFacts,
    UserFacts,
    as_utc,
)
from app.access.models import (
    AccessRequest,
    Capability,
    Grant,
    Group,
    GroupMember,
    PolicyState,
    RbacChange,
)
from app.access.policy import DecidableScope
from app.access.schemas import ChangeQuery, DecisionQuery
from app.identity import User, UserStatus
from app.models.audit import AtlasAuditLog


def _grant_facts(g: Grant) -> GrantFacts:
    return GrantFacts(
        g.id,
        g.subject_type,
        g.subject_id,
        g.effect,
        g.target_kind,
        g.target,
        as_utc(g.expires_at),
    )


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
        return [_grant_facts(g) for g in rows]

    async def group_grants(self, group_ids: Iterable[UUID]) -> list[GrantFacts]:
        """Every grant whose subject is one of `group_ids`, expired ones included."""
        ids = list(group_ids)
        if not ids:
            return []
        rows = (
            (
                await self._db.execute(
                    select(Grant)
                    .where(
                        col(Grant.subject_type) == SUBJECT_GROUP,
                        col(Grant.subject_id).in_(ids),
                    )
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        return [_grant_facts(g) for g in rows]

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

    async def lock_for_write(self) -> int:
        """Serialize admin writes: take a row lock on policy_state (spec §9).

        On Postgres, `FOR UPDATE` blocks a concurrent writer until this
        transaction commits or rolls back, so two admin writes never race
        past each other's application-level checks (duplicate names,
        parent cycles, in-use deletes). SQLite's dialect silently drops
        `FOR UPDATE` at compile time, but aiosqlite serializes writers to
        one connection anyway, so the same call is a safe no-op there.

        Returns the current policy_version, read under the lock.
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
        return version

    async def ensure_policy_state(self) -> None:
        if await self._db.get(PolicyState, 1, populate_existing=True) is None:
            self._db.add(PolicyState(id=1, policy_version=1))
            await self._db.flush()

    async def insert_user_if_absent(self, user: User) -> bool:
        """Stage `user` in a SAVEPOINT; False (nothing staged) when a row with
        the same identity already exists, e.g. a concurrent sign-in won."""
        try:
            async with self._db.begin_nested():
                self._db.add(user)
        except IntegrityError:
            return False
        return True

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

    async def list_users(self, tenant: str, query: str, limit: int) -> list[User]:
        stmt = select(User).where(col(User.tenant) == tenant)
        if query:
            stmt = stmt.where(
                or_(
                    col(User.email).icontains(query, autoescape=True),
                    col(User.display_name).icontains(query, autoescape=True),
                )
            )
        stmt = (
            stmt.order_by(col(User.email))
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def list_changes(
        self,
        tenant: str,
        query: ChangeQuery,
        after: tuple[datetime, UUID] | None = None,
    ) -> list[tuple[RbacChange, User | None]]:
        """Changes in `tenant`, newest first, each with its actor when that
        actor is a user of the same tenant; returns up to `query.limit + 1`
        rows so the caller can tell whether a next page exists."""
        stmt = (
            select(RbacChange, User)
            .outerjoin(
                User,
                and_(
                    col(User.id) == col(RbacChange.actor_user_id),
                    col(User.tenant) == tenant,
                ),
            )
            .where(col(RbacChange.tenant) == tenant)
        )
        at, row_id = col(RbacChange.at), col(RbacChange.id)
        stmt = (
            stmt.where(
                *_equal_where(
                    (col(RbacChange.actor_user_id), query.actor_user_id),
                    (col(RbacChange.object_type), query.object_type),
                    (col(RbacChange.action), query.action),
                    (col(RbacChange.object_id), query.object_id),
                )
            )
            .where(*_window(at, query.since, query.until))
            .where(*_older_than(at, row_id, after))
            .order_by(at.desc(), row_id.desc())
            .limit(query.limit + 1)
            .execution_options(populate_existing=True)
        )
        # Same SQLModel tuple typing quirk as list_members.
        return list(
            cast(
                "Sequence[tuple[RbacChange, User | None]]",
                (await self._db.execute(stmt)).tuples().all(),
            )
        )

    async def list_decisions(
        self,
        tenant: str,
        query: DecisionQuery,
        after: tuple[datetime, UUID] | None = None,
    ) -> list[tuple[AtlasAuditLog, User]]:
        """Atlas tool decisions by users of `tenant`, newest first. The inner
        join drops rows with no user (legacy and anonymous rows) and fails
        closed on tenant; returns up to `query.limit + 1` rows."""
        stmt = (
            select(AtlasAuditLog, User)
            .join(User, col(User.id) == col(AtlasAuditLog.user_id))
            .where(col(User.tenant) == tenant)
        )
        at, row_id = col(AtlasAuditLog.created_at), col(AtlasAuditLog.id)
        stmt = (
            stmt.where(
                *_equal_where(
                    (col(AtlasAuditLog.user_id), query.user_id),
                    (col(AtlasAuditLog.decision), query.decision),
                    (col(AtlasAuditLog.surface), query.surface),
                    (col(AtlasAuditLog.tool), query.tool),
                    (col(AtlasAuditLog.auth_method), query.auth_method),
                )
            )
            .where(*_window(at, query.since, query.until))
            .where(*_older_than(at, row_id, after))
            .order_by(at.desc(), row_id.desc())
            .limit(query.limit + 1)
        )
        # Same SQLModel tuple typing quirk as list_members.
        return list(
            cast(
                "Sequence[tuple[AtlasAuditLog, User]]",
                (await self._db.execute(stmt)).tuples().all(),
            )
        )

    async def decision_counts_by_day(
        self, tenant: str, since: datetime
    ) -> list[tuple[date, str, int]]:
        """(UTC day, decision, count) for `tenant`'s users since `since`."""
        day = self._utc_day(col(AtlasAuditLog.created_at))
        stmt = (
            select(day, col(AtlasAuditLog.decision), func.count())
            .join(User, col(User.id) == col(AtlasAuditLog.user_id))
            .where(col(User.tenant) == tenant, col(AtlasAuditLog.created_at) >= since)
            .group_by(day, col(AtlasAuditLog.decision))
        )
        rows = cast(
            "Sequence[tuple[date | str, str, int]]",
            (await self._db.execute(stmt)).tuples().all(),
        )
        # SQLite's date() returns ISO text; Postgres returns a date.
        return [
            (d if isinstance(d, date) else date.fromisoformat(d), decision, count)
            for d, decision, count in rows
        ]

    async def top_deny_reasons(
        self, tenant: str, since: datetime, limit: int
    ) -> list[tuple[str | None, int]]:
        count = func.count().label("n")
        stmt = (
            select(col(AtlasAuditLog.deny_reason), count)
            .join(User, col(User.id) == col(AtlasAuditLog.user_id))
            .where(
                col(User.tenant) == tenant,
                col(AtlasAuditLog.created_at) >= since,
                col(AtlasAuditLog.decision) == "deny",
            )
            .group_by(col(AtlasAuditLog.deny_reason))
            .order_by(count.desc(), col(AtlasAuditLog.deny_reason).asc().nulls_last())
            .limit(limit)
        )
        return list(
            cast(
                "Sequence[tuple[str | None, int]]",
                (await self._db.execute(stmt)).tuples().all(),
            )
        )

    async def top_denied_users(
        self, tenant: str, since: datetime, limit: int
    ) -> list[tuple[UUID, str, int]]:
        """(user id, display name, denials); never selects an email."""
        count = func.count().label("n")
        stmt = (
            select(col(User.id), col(User.display_name), count)
            .join(AtlasAuditLog, col(AtlasAuditLog.user_id) == col(User.id))
            .where(
                col(User.tenant) == tenant,
                col(AtlasAuditLog.created_at) >= since,
                col(AtlasAuditLog.decision) == "deny",
            )
            .group_by(col(User.id), col(User.display_name))
            .order_by(count.desc(), col(User.display_name), col(User.id))
            .limit(limit)
        )
        return list(
            cast(
                "Sequence[tuple[UUID, str, int]]",
                (await self._db.execute(stmt)).tuples().all(),
            )
        )

    def _utc_day(self, column: Mapped[datetime]) -> ColumnElement[Any]:
        """The UTC calendar day of a timestamp column. Postgres's date() of a
        timestamptz follows the session time zone, so convert to UTC first;
        SQLite stores naive UTC already."""
        if self._db.get_bind().dialect.name == "postgresql":
            return func.date(func.timezone("UTC", column))
        return func.date(column)

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

    # ---- access requests (phase 5) ---------------------------------------

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

    async def count_pending(self, user_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(AccessRequest)
            .where(
                col(AccessRequest.user_id) == user_id,
                col(AccessRequest.status) == "pending",
            )
        )
        return (await self._db.execute(stmt)).scalar_one()

    async def pending_request(
        self, user_id: UUID, kind: str, target: str
    ) -> AccessRequest | None:
        stmt = (
            select(AccessRequest)
            .where(
                col(AccessRequest.user_id) == user_id,
                col(AccessRequest.kind) == kind,
                col(AccessRequest.target) == target,
                col(AccessRequest.status) == "pending",
            )
            .execution_options(populate_existing=True)
        )
        return (await self._db.execute(stmt)).scalars().first()

    async def request(self, request_id: UUID) -> AccessRequest | None:
        return await self._db.get(AccessRequest, request_id, populate_existing=True)

    async def request_for_update(self, request_id: UUID) -> AccessRequest | None:
        """Re-read a request under a row lock (Postgres) inside a decision."""
        stmt = (
            select(AccessRequest)
            .where(col(AccessRequest.id) == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_own_requests(
        self, tenant: str, user_id: UUID, limit: int
    ) -> list[AccessRequest]:
        stmt = (
            select(AccessRequest)
            .where(
                col(AccessRequest.tenant) == tenant,
                col(AccessRequest.user_id) == user_id,
            )
            .order_by(
                col(AccessRequest.created_at).desc(), col(AccessRequest.id).desc()
            )
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def list_decidable(
        self,
        tenant: str,
        scope: DecidableScope,
        status: str | None,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[tuple[AccessRequest, User]]:
        """Requests in `scope`, newest first, with their requester; returns up
        to `limit + 1` rows so the caller can tell whether a next page exists."""
        stmt = (
            select(AccessRequest, User)
            .join(User, col(User.id) == col(AccessRequest.user_id))
            .where(_decidable(tenant, scope))
        )
        if status is not None:
            stmt = stmt.where(col(AccessRequest.status) == status)
        if after is not None:
            at, row_id = after
            stmt = stmt.where(
                or_(
                    col(AccessRequest.created_at) < at,
                    and_(
                        col(AccessRequest.created_at) == at,
                        col(AccessRequest.id) < row_id,
                    ),
                )
            )
        stmt = (
            stmt.order_by(
                col(AccessRequest.created_at).desc(), col(AccessRequest.id).desc()
            )
            .limit(limit + 1)
            .execution_options(populate_existing=True)
        )
        # Same SQLModel tuple typing quirk as list_members.
        rows = cast(
            "Sequence[tuple[AccessRequest, User]]",
            (await self._db.execute(stmt)).tuples().all(),
        )
        return list(rows)

    async def count_decidable(self, tenant: str, scope: DecidableScope) -> int:
        """Pending requests in `scope` (the approvals badge)."""
        stmt = (
            select(func.count())
            .select_from(AccessRequest)
            .where(_decidable(tenant, scope), col(AccessRequest.status) == "pending")
        )
        return (await self._db.execute(stmt)).scalar_one()

    async def finish_request(
        self,
        request_id: UUID,
        tenant: str,
        status: str,
        *,
        decided_by: UUID | None,
        note: str,
        requester: UUID | None = None,
    ) -> int:
        """Move a still-pending request to `status`; returns the rows changed
        (0 when it was no longer pending, or not the requester's). Staged:
        the caller commits."""
        conditions = [
            col(AccessRequest.id) == request_id,
            col(AccessRequest.tenant) == tenant,
            col(AccessRequest.status) == "pending",
        ]
        if requester is not None:
            conditions.append(col(AccessRequest.user_id) == requester)
        result = cast(
            "CursorResult[Any]",
            await self._db.execute(
                update(AccessRequest)
                .where(*conditions)
                .values(
                    status=status,
                    decided_by=decided_by,
                    decided_at=datetime.now(UTC),
                    decision_note=note,
                )
            ),
        )
        return result.rowcount

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

    async def all_group_grants(self, tenant: str) -> list[GrantFacts]:
        """Every grant held by a group in `tenant`, expired ones included."""
        stmt = (
            select(Grant)
            .join(Group, col(Group.id) == col(Grant.subject_id))
            .where(
                col(Grant.subject_type) == SUBJECT_GROUP,
                col(Group.tenant) == tenant,
            )
            .execution_options(populate_existing=True)
        )
        return [_grant_facts(g) for g in (await self._db.execute(stmt)).scalars()]


def _decidable(tenant: str, scope: DecidableScope) -> ColumnElement[bool]:
    """The WHERE clause for `scope` (P5-D9), always tenant-filtered."""
    kinds: list[ColumnElement[bool]] = []
    if scope.role_and_resource:
        kinds.append(col(AccessRequest.kind).in_(("role", "resource")))
    if scope.all_groups:
        kinds.append(col(AccessRequest.kind) == "group")
    elif scope.group_ids:
        kinds.append(
            and_(
                col(AccessRequest.kind) == "group",
                col(AccessRequest.target).in_(sorted(str(g) for g in scope.group_ids)),
            )
        )
    clause = and_(
        col(AccessRequest.tenant) == tenant, or_(*kinds) if kinds else false()
    )
    if scope.user_id is not None:
        clause = and_(clause, col(AccessRequest.user_id) != scope.user_id)
    return clause


def _equal_where(*filters: tuple[Mapped[Any], object]) -> list[ColumnElement[bool]]:
    """`column == value` for every filter that was given (None = not filtered)."""
    return [column == value for column, value in filters if value is not None]


def _window(
    column: Mapped[datetime], since: datetime | None, until: datetime | None
) -> list[ColumnElement[bool]]:
    """`since` inclusive, `until` exclusive, compared in UTC."""
    clauses: list[ColumnElement[bool]] = []
    if since is not None:
        clauses.append(column >= since.astimezone(UTC))
    if until is not None:
        clauses.append(column < until.astimezone(UTC))
    return clauses


def _older_than(
    at: Mapped[datetime],
    row_id: Mapped[UUID],
    after: tuple[datetime, UUID] | None,
) -> list[ColumnElement[bool]]:
    """Keyset position for a `(at, id)` descending walk: rows after the cursor."""
    if after is None:
        return []
    moment, last_id = after
    return [or_(at < moment, and_(at == moment, row_id < last_id))]

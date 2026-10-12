"""Reads for the audit views: the access-change log and atlas tool decisions."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped
from sqlmodel import col, select

from app.access.models import RbacChange
from app.access.repositories.filters import equal_where
from app.access.schemas import ChangeQuery, DecisionQuery
from app.identity import User
from app.models.audit import AtlasAuditLog


class AuditRepository:
    """Reads for the audit views: the access-change log and atlas decisions."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

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
                *equal_where(
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
        # SQLModel's tuple typing quirk: see GroupRepository.list_members.
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
                *equal_where(
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
        # SQLModel's tuple typing quirk: see GroupRepository.list_members.
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

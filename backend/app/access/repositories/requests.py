"""Access requests: the requester's own, the decidable queue and decisions."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import ColumnElement, CursorResult, and_, false, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.access.models import AccessRequest
from app.access.policy import DecidableScope
from app.access.repositories.filters import equal_where
from app.identity import User


class RequestRepository:
    """Access requests."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

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
        statuses: Sequence[str] | None,
        after: tuple[datetime, UUID] | None,
        limit: int,
        *,
        user_id: UUID | None = None,
    ) -> list[tuple[AccessRequest, User]]:
        """Requests in `scope` (any of `statuses`; None = every status; only
        `user_id`'s when given), newest first, with their requester; returns up
        to `limit + 1` rows so the caller can tell whether a next page exists."""
        stmt = (
            select(AccessRequest, User)
            .join(User, col(User.id) == col(AccessRequest.user_id))
            .where(_decidable(tenant, scope))
            .where(*equal_where((col(AccessRequest.user_id), user_id)))
        )
        if statuses is not None:
            stmt = stmt.where(col(AccessRequest.status).in_(statuses))
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
        # SQLModel's tuple typing quirk: see GroupRepository.list_members.
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

"""Grants: the evaluator's facts and the rows administration reads."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.access.facts import SUBJECT_GROUP, SUBJECT_USER, GrantFacts, as_utc
from app.access.models import Grant, Group


def _grant_facts(g: Grant) -> GrantFacts:
    return GrantFacts(
        g.id,
        g.subject_type,
        g.subject_id,
        g.effect,
        g.target_kind,
        g.target,
        as_utc(g.expires_at),
        g.row_scope,
    )


class GrantRepository:
    """Grants held by groups and users."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

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

    async def count_grants(self, subject_type: str, subject_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Grant)
            .where(
                col(Grant.subject_type) == subject_type,
                col(Grant.subject_id) == subject_id,
            )
        )
        return (await self._db.execute(stmt)).scalar_one()

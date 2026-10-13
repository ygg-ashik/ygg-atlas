"""SQL building blocks the credential repositories share. No business decisions."""

from datetime import datetime
from typing import Any, Final, cast
from uuid import UUID

from sqlalchemy import ColumnElement, CursorResult, Delete, Result, Update, and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped
from sqlmodel import col, select

from app.identity.models import ApiToken, OAuthCode

TOKEN_ID: Final = col(ApiToken.id)
CODE_ID: Final = col(OAuthCode.id)


def _rowcount(result: Result[Any]) -> int:
    # A DML statement always executes through a cursor, so this is a CursorResult
    # at runtime; AsyncSession.execute only types it as the base Result.
    return cast("CursorResult[Any]", result).rowcount


async def run_dml(db: AsyncSession, statement: Update | Delete) -> int:
    """Run one UPDATE or DELETE and return the rows it matched. "fetch" keeps
    rows already loaded in this session in step with the database."""
    result = await db.execute(statement.execution_options(synchronize_session="fetch"))
    return _rowcount(result)


def live_token(now: datetime) -> ColumnElement[bool]:
    return and_(col(ApiToken.revoked_at).is_(None), col(ApiToken.expires_at) > now)


def locked_in_id_order(
    row_id: Mapped[UUID], where: ColumnElement[bool]
) -> ColumnElement[bool]:
    """`id IN (SELECT id ... ORDER BY id FOR UPDATE)`: one statement that locks the
    matching rows in id order before it changes them, so two multi-row writes over
    overlapping rows (revokes by family, client or user; spent codes; GC) queue
    instead of deadlocking. PostgreSQL keeps a locking subquery as its own sorted,
    locking scan (verified with EXPLAIN). SQLite ignores FOR UPDATE."""
    ids = (
        select(row_id).where(where).order_by(row_id).with_for_update().scalar_subquery()
    )
    return row_id.in_(ids)


async def revoke_live(
    db: AsyncSession, owned_by: ColumnElement[bool], reason: str, now: datetime
) -> int:
    """Revokes the not-yet-revoked token rows matching `owned_by`, locked in id
    order; never overwrites an earlier reason."""
    unrevoked = col(ApiToken.revoked_at).is_(None)
    return await run_dml(
        db,
        update(ApiToken)
        .where(locked_in_id_order(TOKEN_ID, and_(owned_by, unrevoked)), unrevoked)
        .values(revoked_at=now, revoked_reason=reason),
    )

"""Database access for pending authorization requests and authorization codes."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, and_, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.identity.models import OAuthAuthorizationRequest, OAuthCode
from app.identity.repository.statements import CODE_ID, locked_in_id_order, run_dml


class CodeRepository:
    """Authorization requests and codes, each usable once. Writes are staged; the
    calling service commits."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def pending_request(
        self, request_hash: str, now: datetime
    ) -> OAuthAuthorizationRequest | None:
        result = await self._db.execute(
            select(OAuthAuthorizationRequest).where(
                col(OAuthAuthorizationRequest.id) == request_hash,
                col(OAuthAuthorizationRequest.consumed_at).is_(None),
                col(OAuthAuthorizationRequest.expires_at) > now,
            )
        )
        return result.scalar_one_or_none()

    async def consume_request(
        self, request_hash: str, now: datetime
    ) -> OAuthAuthorizationRequest | None:
        """Single use: exactly one concurrent consent sees the request."""
        consumed = await run_dml(
            self._db,
            update(OAuthAuthorizationRequest)
            .where(
                col(OAuthAuthorizationRequest.id) == request_hash,
                col(OAuthAuthorizationRequest.consumed_at).is_(None),
                col(OAuthAuthorizationRequest.expires_at) > now,
            )
            .values(consumed_at=now),
        )
        if consumed != 1:
            return None
        return await self._db.get(
            OAuthAuthorizationRequest, request_hash, populate_existing=True
        )

    async def code_by_hash(self, code_hash: str) -> OAuthCode | None:
        result = await self._db.execute(
            select(OAuthCode).where(col(OAuthCode.code_hash) == code_hash)
        )
        return result.scalar_one_or_none()

    async def code(self, code_id: UUID, *, fresh: bool = False) -> OAuthCode | None:
        return await self._db.get(OAuthCode, code_id, populate_existing=fresh)

    async def mark_code_used(self, code_id: UUID, now: datetime) -> bool:
        """Single use: exactly one caller ever sees True, on SQLite and on PG
        READ COMMITTED (the loser's UPDATE waits for the winner's row lock,
        re-checks used_at and matches 0 rows)."""
        return (
            await run_dml(
                self._db,
                update(OAuthCode)
                .where(
                    col(OAuthCode.id) == code_id,
                    col(OAuthCode.used_at).is_(None),
                    col(OAuthCode.expires_at) > now,
                )
                .values(used_at=now),
            )
            == 1
        )

    async def spend_user_codes(self, user_id: UUID, now: datetime) -> int:
        """Deletes the user's unused, unexpired codes (revoke-all: a code consented
        to before it must not mint a pair after it). Deleted rather than marked
        used, so a later exchange is a dead code, not a false reuse alarm. Call
        after revoke_user_tokens, which holds the user row."""
        return await self._spend_codes(col(OAuthCode.user_id) == user_id, now)

    async def spend_client_codes(self, client_id: str, now: datetime) -> int:
        """The client's unused, unexpired codes, as spend_user_codes."""
        return await self._spend_codes(col(OAuthCode.client_id) == client_id, now)

    async def _spend_codes(self, owned_by: ColumnElement[bool], now: datetime) -> int:
        unused = and_(
            owned_by, col(OAuthCode.used_at).is_(None), col(OAuthCode.expires_at) > now
        )
        return await run_dml(
            self._db, delete(OAuthCode).where(locked_in_id_order(CODE_ID, unused))
        )

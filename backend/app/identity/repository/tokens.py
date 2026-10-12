"""Database access for api_tokens rows one at a time, or by owner (user, client)."""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.identity.api_tokens import REVOKED_ROTATED
from app.identity.models import ApiToken, User
from app.identity.repository.statements import live_token, revoke_live, run_dml


class TokenRepository:
    """Token rows of every kind. Writes are staged; the calling service commits."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def token(self, token_id: UUID, *, fresh: bool = False) -> ApiToken | None:
        return await self._db.get(ApiToken, token_id, populate_existing=fresh)

    async def token_by_hash(self, token_hash: str) -> ApiToken | None:
        result = await self._db.execute(
            select(ApiToken).where(col(ApiToken.token_hash) == token_hash)
        )
        return result.scalar_one_or_none()

    async def list_tokens(
        self,
        *,
        tenant: str,
        kinds: Collection[str],
        user_id: UUID | None = None,
        include_revoked: bool = False,
        limit: int = 200,
    ) -> list[ApiToken]:
        statement = (
            select(ApiToken)
            .join(User, col(User.id) == col(ApiToken.user_id))
            .where(col(User.tenant) == tenant, col(ApiToken.kind).in_(list(kinds)))
        )
        if user_id is not None:
            statement = statement.where(col(ApiToken.user_id) == user_id)
        if not include_revoked:
            statement = statement.where(col(ApiToken.revoked_at).is_(None))
        statement = statement.order_by(col(ApiToken.created_at).desc()).limit(limit)
        return list((await self._db.execute(statement)).scalars().all())

    async def count_live(self, user_id: UUID, kind: str, now: datetime) -> int:
        result = await self._db.execute(
            select(func.count())
            .select_from(ApiToken)
            .where(
                col(ApiToken.user_id) == user_id,
                col(ApiToken.kind) == kind,
                live_token(now),
            )
        )
        return result.scalar_one()

    async def revoke_token(self, token_id: UUID, reason: str, now: datetime) -> bool:
        return (
            await run_dml(
                self._db,
                update(ApiToken)
                .where(col(ApiToken.id) == token_id, col(ApiToken.revoked_at).is_(None))
                .values(revoked_at=now, revoked_reason=reason),
            )
            == 1
        )

    async def mark_rotated(self, token_id: UUID, now: datetime) -> bool:
        """Exactly one concurrent refresh of a token sees True (D6)."""
        return await self.revoke_token(token_id, REVOKED_ROTATED, now)

    async def revoke_user_tokens(
        self, user_id: UUID, reason: str, now: datetime
    ) -> int:
        """Every token of the user. The user row is locked first (FOR NO KEY UPDATE,
        PostgreSQL only): an issuer holding it FOR SHARE (lock_user) commits its
        pair before this revoke reads the token rows, and a later one waits until
        the revoke commits. User row before token rows, like issuers: no cycle."""
        if self._db.get_bind().dialect.name == "postgresql":
            await self._db.execute(
                select(col(User.id))
                .where(col(User.id) == user_id)
                .with_for_update(key_share=True)
            )
        return await revoke_live(
            self._db, col(ApiToken.user_id) == user_id, reason, now
        )

    async def revoke_client_tokens(
        self, client_id: str, reason: str, now: datetime
    ) -> int:
        """The client's live rows only. An expired row needs no revoke, and leaving
        it out keeps this lock set (client row, then unexpired tokens) disjoint
        from delete_stale's (tokens expired or revoked 30 days ago, then client
        rows), so the two never lock the same rows in opposite order."""
        return await revoke_live(
            self._db,
            and_(
                col(ApiToken.client_id) == client_id,
                col(ApiToken.expires_at) > now,
            ),
            reason,
            now,
        )

    async def touch_token(self, token_id: UUID, now: datetime) -> None:
        await run_dml(
            self._db,
            update(ApiToken)
            .where(col(ApiToken.id) == token_id)
            .values(last_used_at=now),
        )

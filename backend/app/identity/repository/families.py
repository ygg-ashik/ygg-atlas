"""Database access for OAuth token families: the api_tokens rows one consent
issued, their lock, and the connected-app views built from them."""

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.identity.api_tokens import TokenKind
from app.identity.models import ApiToken, OAuthClient
from app.identity.repository.statements import live_token, revoke_live


@dataclass(frozen=True, slots=True)
class ConnectedAppRow:
    """One OAuth family with a live refresh token, joined to its client."""

    family_id: UUID
    client_id: str
    client_name: str | None
    redirect_uris: tuple[str, ...]
    created_at: datetime  # when the family began (its first token)
    last_used_at: datetime | None  # latest use of any token in the family
    expires_at: datetime  # the live refresh token's expiry


class FamilyRepository:
    """Token families. Writes are staged; the calling service commits."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def lock_family(self, family_id: UUID) -> None:
        """Serialise every change to one OAuth family until this transaction ends.

        Without it a family revoke can land between a rotation's mark_rotated and
        the insert of the new pair (or during a grace issue) and miss the new rows,
        leaving a live pair in a revoked family. PostgreSQL: a transaction-scoped
        advisory lock keyed by the family id. SQLite serialises writers already, so
        it is a no-op there.
        """
        if self._db.get_bind().dialect.name != "postgresql":
            return
        await self._db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:family, 0))"),
            {"family": str(family_id)},
        )

    async def revoke_family(self, family_id: UUID, reason: str, now: datetime) -> int:
        """Revokes the family's live rows under the family lock."""
        await self.lock_family(family_id)
        return await revoke_live(
            self._db, col(ApiToken.family_id) == family_id, reason, now
        )

    async def family_has_live_token(self, family_id: UUID, now: datetime) -> bool:
        result = await self._db.execute(
            select(col(ApiToken.id))
            .where(col(ApiToken.family_id) == family_id, live_token(now))
            .limit(1)
        )
        return result.first() is not None

    async def connected_apps(
        self, user_id: UUID, now: datetime
    ) -> list[ConnectedAppRow]:
        """One row per family that still has a live refresh token."""
        live = (
            await self._db.execute(
                select(ApiToken, OAuthClient)
                .join(
                    OAuthClient, col(OAuthClient.client_id) == col(ApiToken.client_id)
                )
                .where(
                    col(ApiToken.user_id) == user_id,
                    col(ApiToken.kind) == TokenKind.OAUTH_REFRESH,
                    col(ApiToken.family_id).is_not(None),
                    col(OAuthClient.revoked_at).is_(None),
                    live_token(now),
                )
                .order_by(col(ApiToken.expires_at))
            )
        ).all()
        # A grace refresh (D6) may leave two live refresh tokens in one family
        # for a moment; the later expiry wins.
        latest: dict[UUID, tuple[ApiToken, OAuthClient]] = {}
        for token, client in live:
            if token.family_id is not None:
                latest[token.family_id] = (token, client)
        spans = await self._family_spans(list(latest))
        return [
            ConnectedAppRow(
                family_id=family_id,
                client_id=client.client_id,
                client_name=client.client_name,
                redirect_uris=tuple(client.redirect_uris),
                created_at=spans[family_id][0],
                last_used_at=spans[family_id][1],
                expires_at=token.expires_at,
            )
            for family_id, (token, client) in latest.items()
        ]

    async def _family_spans(
        self, family_ids: list[UUID]
    ) -> dict[UUID, tuple[datetime, datetime | None]]:
        if not family_ids:
            return {}
        rows = (
            await self._db.execute(
                select(
                    col(ApiToken.family_id),
                    func.min(col(ApiToken.created_at)),
                    func.max(col(ApiToken.last_used_at)),
                )
                .where(col(ApiToken.family_id).in_(family_ids))
                .group_by(col(ApiToken.family_id))
            )
        ).all()
        return {
            cast(UUID, family): (cast(datetime, first), cast("datetime | None", last))
            for family, first, last in rows
        }

    async def live_family_counts(self, now: datetime) -> dict[str, int]:
        """client_id -> number of families with a live refresh token."""
        rows = (
            await self._db.execute(
                select(
                    col(ApiToken.client_id),
                    func.count(func.distinct(col(ApiToken.family_id))),
                )
                .where(
                    col(ApiToken.kind) == TokenKind.OAUTH_REFRESH,
                    col(ApiToken.client_id).is_not(None),
                    live_token(now),
                )
                .group_by(col(ApiToken.client_id))
            )
        ).all()
        return {cast(str, client): int(count) for client, count in rows}

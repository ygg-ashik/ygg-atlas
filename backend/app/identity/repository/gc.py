"""Garbage collection of dead credential rows."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import and_, delete, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.identity.api_tokens import CLIENT_IDLE_GC, TokenKind
from app.identity.models import (
    ApiToken,
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthCode,
)
from app.identity.repository.statements import TOKEN_ID, locked_in_id_order, run_dml

# Pending authorizations and codes live minutes, so a day is generous; dead OAuth
# token rows are kept a month for investigations.
PENDING_RETENTION: Final = timedelta(days=1)
OAUTH_TOKEN_RETENTION: Final = timedelta(days=30)
_OAUTH_KINDS: Final = (TokenKind.OAUTH_ACCESS, TokenKind.OAUTH_REFRESH)


@dataclass(frozen=True, slots=True)
class GcCounts:
    codes: int
    requests: int
    tokens: int
    clients: int


class GcRepository:
    """Deletes stale OAuth rows. The calling service commits."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def delete_stale(self, now: datetime) -> GcCounts:
        """Codes and pending authorizations older than a day; OAuth token rows expired
        or revoked over 30 days ago; then clients revoked or idle for 90 days that
        no row references any more. PAT and service rows are never deleted."""
        pending_cutoff = now - PENDING_RETENTION
        codes = await run_dml(
            self._db,
            delete(OAuthCode).where(col(OAuthCode.created_at) < pending_cutoff),
        )
        requests = await run_dml(
            self._db,
            delete(OAuthAuthorizationRequest).where(
                col(OAuthAuthorizationRequest.created_at) < pending_cutoff
            ),
        )
        token_cutoff = now - OAUTH_TOKEN_RETENTION
        tokens = await run_dml(  # id order, like the revokes: no deadlock
            self._db,
            delete(ApiToken).where(
                locked_in_id_order(
                    TOKEN_ID,
                    and_(
                        col(ApiToken.kind).in_(_OAUTH_KINDS),
                        or_(
                            col(ApiToken.expires_at) < token_cutoff,
                            col(ApiToken.revoked_at) < token_cutoff,
                        ),
                    ),
                )
            ),
        )
        clients = await self._delete_dead_clients(now - CLIENT_IDLE_GC)
        return GcCounts(codes=codes, requests=requests, tokens=tokens, clients=clients)

    async def _delete_dead_clients(self, idle_cutoff: datetime) -> int:
        client_id = col(OAuthClient.client_id)
        referenced = [
            select(col(ApiToken.id)).where(col(ApiToken.client_id) == client_id),
            select(col(OAuthCode.id)).where(col(OAuthCode.client_id) == client_id),
            select(col(OAuthAuthorizationRequest.id)).where(
                col(OAuthAuthorizationRequest.client_id) == client_id
            ),
        ]
        last_activity = func.coalesce(
            col(OAuthClient.last_used_at), col(OAuthClient.registered_at)
        )
        return await run_dml(
            self._db,
            delete(OAuthClient).where(
                or_(
                    col(OAuthClient.revoked_at).is_not(None),
                    last_activity < idle_cutoff,
                ),
                *(~query.exists() for query in referenced),
            ),
        )

"""RFC 7009 revocation of an OAuth token's family, and the stale-row sweep."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from uuid import UUID

import structlog

from app.identity.api_tokens import (
    EVENT_GC,
    REVOKED_OAUTH_REVOKE,
    TokenKind,
    hash_secret,
    kind_of,
)
from app.identity.models import CredentialEvent
from app.identity.oauth.families import Family, TokenFamilies
from app.identity.oauth.values import AccessTokenRef, GcReport
from app.identity.repository import CredentialRepository

logger = structlog.get_logger()


class RevocationService:
    """Finds and revokes OAuth tokens a client holds; deletes dead rows."""

    def __init__(
        self,
        creds: CredentialRepository,
        clock: Callable[[], datetime],
        families: TokenFamilies,
    ) -> None:
        self._creds = creds
        self._clock = clock
        self._families = families

    async def find_access_token(self, raw_access: str) -> AccessTokenRef | None:
        """RFC 7009 lookup of an OAuth access token: expired, revoked or owned by a
        disabled user alike, and without touching `last_used_at` (unlike the bearer
        door), so a client can always revoke what it holds. None for anything else."""
        if kind_of(raw_access) is not TokenKind.OAUTH_ACCESS:
            return None
        row = await self._creds.tokens.token_by_hash(hash_secret(raw_access))
        if row is None or row.kind != TokenKind.OAUTH_ACCESS or row.client_id is None:
            return None
        return AccessTokenRef(token_id=row.id, client_id=row.client_id)

    async def revoke_by_token_id(self, token_id: UUID) -> None:
        """RFC 7009: revokes the token's whole family. Unknown and non-OAuth tokens
        are ignored (the endpoint answers 200 regardless)."""
        row = await self._creds.tokens.token(token_id, fresh=True)
        if row is None or row.family_id is None or row.client_id is None:
            return
        family = Family(row.family_id, row.user_id, row.client_id)
        await self._families.revoke(family, REVOKED_OAUTH_REVOKE)

    async def gc(self) -> GcReport:
        """delete_stale, then a credentials.gc event with the counts."""
        counts = await self._creds.gc.delete_stale(self._clock())
        self._creds.add(
            CredentialEvent(event=EVENT_GC, via="system", details=asdict(counts))
        )
        await self._creds.commit()
        logger.info(EVENT_GC, **asdict(counts))
        return counts

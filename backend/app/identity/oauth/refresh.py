"""The refresh-token grant: rotation with reuse detection and a 30 s same-client
grace. Every refresh re-checks the user, mcp:use, the client and the audience."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.identity.api_tokens import (
    EVENT_REFRESH_GRACE,
    EVENT_REFRESHED,
    REVOKED_CROSS_CLIENT,
    REVOKED_REFRESH_REUSE,
    REVOKED_ROTATED,
    TokenKind,
    hash_secret,
    kind_of,
)
from app.identity.clock import as_utc
from app.identity.models import ApiToken
from app.identity.oauth.config import OAuthConfig
from app.identity.oauth.errors import (
    DEAD_REFRESH,
    GrantUnavailableError,
    OAuthGrantError,
)
from app.identity.oauth.families import Family, TokenFamilies, presenter
from app.identity.oauth.values import Eligibility, RefreshGrant, TokenPair
from app.identity.repository import CredentialRepository


class RefreshRotation:
    """Loads refresh tokens and rotates them, once per token."""

    def __init__(
        self,
        creds: CredentialRepository,
        config: OAuthConfig,
        families: TokenFamilies,
    ) -> None:
        self._creds = creds
        self._config = config
        self._families = families

    async def load_refresh(
        self, client_id: str, raw_refresh: str
    ) -> RefreshGrant | None:
        """None for non-refresh or unknown tokens; a cross-client presentation revokes
        the family (no grace across clients). Revoked rows load too: rotation
        decides between grace and reuse. An unexpected database error raises
        GrantUnavailableError."""
        try:
            return await self._load_refresh(client_id, raw_refresh)
        except SQLAlchemyError as exc:
            await self._families.database_error(exc, op="load_refresh")
            raise GrantUnavailableError from None

    async def _load_refresh(
        self, client_id: str, raw_refresh: str
    ) -> RefreshGrant | None:
        if kind_of(raw_refresh) is not TokenKind.OAUTH_REFRESH:
            return None
        row = await self._creds.tokens.token_by_hash(hash_secret(raw_refresh))
        if row is None or row.kind != TokenKind.OAUTH_REFRESH or row.family_id is None:
            return None
        if row.client_id != client_id:
            family = Family(row.family_id, row.user_id, row.client_id or client_id)
            await self._families.revoke(
                family,
                REVOKED_CROSS_CLIENT,
                kind="refresh",
                extra_details=presenter(family.client_id, client_id),
            )
            return None
        return RefreshGrant(
            token_id=row.id,
            family_id=row.family_id,
            client_id=client_id,
            user_id=row.user_id,
            resource=row.audience or "",
            expires_at=as_utc(row.expires_at),
            display=row.prefix,
        )

    async def rotate_refresh(
        self, client_id: str, grant: RefreshGrant, eligible: Eligibility
    ) -> TokenPair:
        """Rotation with reuse detection and a 30 s same-client grace. Every
        refresh re-checks the user, mcp:use, the client and the audience. Raises
        OAuthGrantError, or GrantUnavailableError for a transient failure."""
        return await self._families.db_errors_as_unavailable(
            self._rotate_refresh(client_id, grant, eligible), op="rotate_refresh"
        )

    async def _rotate_refresh(
        self, client_id: str, grant: RefreshGrant, eligible: Eligibility
    ) -> TokenPair:
        row = await self._creds.tokens.token(grant.token_id, fresh=True)
        if (
            row is None
            or row.client_id != client_id
            or row.family_id != grant.family_id
            or row.kind != TokenKind.OAUTH_REFRESH
        ):
            raise OAuthGrantError(DEAD_REFRESH)
        family = Family(grant.family_id, row.user_id, client_id)
        audience = row.audience or ""
        # Held until the commit: a family revoke cannot slip in between marking
        # this token rotated and inserting its successor.
        now = await self._families.enter(family)
        if row.revoked_at is None and as_utc(row.expires_at) <= now:
            await self._creds.rollback()
            raise OAuthGrantError(DEAD_REFRESH)
        if row.revoked_at is not None or not await self._creds.tokens.mark_rotated(
            row.id, now
        ):
            return await self._retry_or_reuse(grant.token_id, family, eligible)
        return await self._families.issue_checked(
            family, audience, eligible, now, EVENT_REFRESHED
        )

    async def _retry_or_reuse(
        self, token_id: UUID, family: Family, eligible: Eligibility
    ) -> TokenPair:
        """The presented token was already rotated or revoked. One revoked for any
        reason but rotation (admin, disable, client or family revoke) is simply dead:
        the legitimate client next refreshing it is no replay, so no alarm and no
        revoke. A rotated one: a same-client retry within the grace gets a fresh
        pair; anything else is reuse. The grace check (the family still has a live
        token) runs under the family lock, so a concurrent revoke either lands first
        and is seen, or waits for the issue and then covers the new pair too."""
        await self._creds.rollback()
        now = await self._families.enter(family)
        row = await self._creds.tokens.token(token_id, fresh=True)
        if (
            row is not None
            and row.revoked_at is not None
            and row.revoked_reason != REVOKED_ROTATED
        ):
            await self._creds.rollback()
            raise OAuthGrantError(DEAD_REFRESH)
        if row is not None and await self._in_grace(row, now):
            audience = row.audience or ""
            return await self._families.issue_checked(
                family, audience, eligible, now, EVENT_REFRESH_GRACE
            )
        await self._families.revoke(family, REVOKED_REFRESH_REUSE, kind="refresh")
        raise OAuthGrantError(DEAD_REFRESH)

    async def _in_grace(self, row: ApiToken, now: datetime) -> bool:
        """A concurrent retry by the same client (already checked) within 30 s, while
        the family is still alive. A family revoke never overwrites 'rotated', hence
        the live-token check."""
        return (
            row.revoked_reason == REVOKED_ROTATED
            and row.revoked_at is not None
            and now - as_utc(row.revoked_at) <= self._config.refresh_grace
            and row.family_id is not None
            and await self._creds.families.family_has_live_token(row.family_id, now)
        )

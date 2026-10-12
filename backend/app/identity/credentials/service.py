"""TokenService: PATs and service tokens for the self-service and admin APIs and the
CLI, and the revoke-all hook access calls when a user is disabled."""

from collections.abc import Callable, Collection
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.identity.api_tokens import CredentialActor, CredentialVia, TokenKind
from app.identity.clock import utcnow
from app.identity.credentials.issuance import IssuedToken, TokenIssuer, TokenRequest
from app.identity.credentials.revocation import ConnectedApp, TokenRevoker
from app.identity.models import ApiToken, CredentialEvent
from app.identity.repository import CredentialRepository, UserRepository

logger = structlog.get_logger()


class TokenService:
    """PATs and service tokens for the self-service and admin APIs and the CLI. It
    composes the issuer and the revoker over one session."""

    def __init__(
        self, db: AsyncSession, clock: Callable[[], datetime] = utcnow
    ) -> None:
        creds = CredentialRepository(db)
        users = UserRepository(db)
        self._creds = creds
        self._issuer = TokenIssuer(creds, users, clock)
        self._revoker = TokenRevoker(creds, users, clock)

    async def create_pat(
        self,
        user_id: UUID,
        *,
        name: str,
        expires_in_days: int | None,
        actor: CredentialActor,
        default_days: int,
        max_days: int,
    ) -> IssuedToken:
        """An active human's personal token: name 1-100 chars, days in 1..max_days
        (default `default_days`), at most MAX_LIVE_PATS live. Writes token.created."""
        return await self._issuer.issue(
            TokenRequest(
                user_id,
                TokenKind.PAT,
                name,
                expires_in_days,
                actor,
                default_days,
                max_days,
            )
        )

    async def create_service_token(
        self,
        service_user_id: UUID,
        *,
        name: str,
        expires_in_days: int | None,
        actor: CredentialActor,
        default_days: int,
        max_days: int,
    ) -> IssuedToken:
        """A token for an active service account; same day rules, no live cap."""
        return await self._issuer.issue(
            TokenRequest(
                service_user_id,
                TokenKind.SERVICE,
                name,
                expires_in_days,
                actor,
                default_days,
                max_days,
            )
        )

    async def list_tokens(
        self,
        *,
        tenant: str,
        user_id: UUID | None = None,
        kinds: Collection[TokenKind] = (TokenKind.PAT, TokenKind.SERVICE),
        include_revoked: bool = False,
    ) -> list[ApiToken]:
        """Tokens in `tenant`, newest first; only one user's when `user_id` is set."""
        return await self._creds.tokens.list_tokens(
            tenant=tenant,
            kinds=[str(kind) for kind in kinds],
            user_id=user_id,
            include_revoked=include_revoked,
        )

    async def revoke_token(
        self,
        token_id: UUID,
        *,
        reason: str,
        actor: CredentialActor,
        owner_id: UUID | None = None,
        tenant: str | None = None,
    ) -> None:
        """Idempotent. Another owner's or tenant's token is CredentialNotFoundError
        (no existence probing). Writes token.revoked."""
        await self._revoker.revoke_token(
            token_id, reason=reason, actor=actor, owner_id=owner_id, tenant=tenant
        )

    async def revoke_all_tokens(
        self, user_id: UUID, *, reason: str, actor: CredentialActor
    ) -> int:
        """Every kind; one tokens.revoked_all event with the count and reason."""
        return await self._revoker.revoke_all_tokens(
            user_id, reason=reason, actor=actor
        )

    async def list_connected_apps(self, user_id: UUID) -> list[ConnectedApp]:
        """One entry per OAuth family with a live refresh token."""
        return await self._revoker.list_connected_apps(user_id)

    async def revoke_family(
        self,
        family_id: UUID,
        *,
        reason: str,
        actor: CredentialActor,
        owner_id: UUID | None = None,
    ) -> None:
        """Revokes every live row of the family; writes oauth.family_revoked. With
        `owner_id`, it must be one of that user's connected apps."""
        await self._revoker.revoke_family(
            family_id, reason=reason, actor=actor, owner_id=owner_id
        )

    async def list_events(
        self, *, tenant: str, user_id: UUID | None = None, limit: int = 100
    ) -> list[CredentialEvent]:
        """credential_events in `tenant`, newest first."""
        return await self._creds.events.list_events(
            tenant=tenant, user_id=user_id, limit=limit
        )


async def revoke_user_tokens(
    user_id: UUID,
    *,
    reason: str,
    actor_user_id: UUID | None,
    via: CredentialVia,
) -> None:
    """Post-commit hook for AccessAdmin.update_user (D18, C5): opens its own session
    from get_session_factory(), revokes every token of every kind, writes
    tokens.revoked_all, and never raises (logs identity.revoke_all_failed). The bearer
    door refuses disabled users regardless."""
    try:
        async with get_session_factory()() as db:
            await TokenService(db).revoke_all_tokens(
                user_id, reason=reason, actor=CredentialActor(actor_user_id, via)
            )
    except Exception as exc:  # a hook: the door refuses disabled users anyway
        logger.error(
            "identity.revoke_all_failed",
            user_id=str(user_id),
            error=type(exc).__name__,
        )

"""Personal and service tokens, connected apps and the single bearer door (D3, D20).

Interface first (D35): auth phase 4 Task 2 lands these signatures so the MCP edge and
the access hooks can code against them; Task 3 fills the bodies. Raw secrets exist
only in `IssuedToken.raw`, once, and are never logged, stored or put in a repr.
"""

import re
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.api_tokens import CredentialActor, CredentialVia, TokenKind
from app.identity.models import ApiToken, CredentialEvent
from app.identity.principal import Principal

SERVICE_ACCOUNT_DOMAIN: Final = "atlas.internal"
_SLUG_SEPARATORS: Final = re.compile(r"[^a-z0-9]+")
_SLUG_MIN, _SLUG_MAX = 3, 40


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A freshly minted token: the stored row and the raw value, shown once (D3)."""

    token: ApiToken
    raw: str = field(repr=False)  # never logged or stored


@dataclass(frozen=True, slots=True)
class AuthenticatedBearer:
    """What the bearer door hands the MCP token verifier (C11)."""

    principal: Principal  # auth_method oauth|pat|service, token_id and client_id set
    expires_at: datetime
    audience: str | None  # OAuth: the bound audience; PAT/service: None (use current)
    display_prefix: str


@dataclass(frozen=True, slots=True)
class ConnectedApp:
    """One OAuth consent (a token family) that can still refresh."""

    family_id: UUID
    client_id: str
    client_name: str | None
    redirect_host: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime


def service_account_email(name: str) -> str | None:
    """The `svc-<slug>@atlas.internal` email for a service-account name, or None when
    the slug is not 3-40 lowercase letters, digits or dashes (D13, ruling C5)."""
    slug = _SLUG_SEPARATORS.sub("-", name.strip().lower()).strip("-")
    if not _SLUG_MIN <= len(slug) <= _SLUG_MAX:
        return None
    return f"svc-{slug}@{SERVICE_ACCOUNT_DOMAIN}"


async def authenticate_bearer(
    db: AsyncSession, raw: str, now: datetime | None = None
) -> AuthenticatedBearer:
    """Raises InvalidTokenError (unknown, expired, revoked, wrong kind, refresh token,
    revoked client) or ForbiddenError (user disabled). Never includes token material
    in the message."""
    raise NotImplementedError


async def principal_for_user(db: AsyncSession, user_id: UUID) -> Principal | None:
    """Active users only; auth_method 'service' for service accounts, 'pat' otherwise.
    Used by the MCP edge to evaluate a user's Policy (eligibility, D34)."""
    raise NotImplementedError


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
    raise NotImplementedError


class TokenService:
    """PATs and service tokens for the self-service and admin APIs and the CLI."""

    def __init__(
        self, db: AsyncSession, clock: Callable[[], datetime] = _utcnow
    ) -> None:
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError

    async def list_tokens(
        self,
        *,
        tenant: str,
        user_id: UUID | None = None,
        kinds: Collection[TokenKind] = (TokenKind.PAT, TokenKind.SERVICE),
        include_revoked: bool = False,
    ) -> list[ApiToken]:
        """Tokens in `tenant`, newest first; only one user's when `user_id` is set."""
        raise NotImplementedError

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
        raise NotImplementedError

    async def revoke_all_tokens(
        self, user_id: UUID, *, reason: str, actor: CredentialActor
    ) -> int:
        """Every kind; one tokens.revoked_all event with the count and reason."""
        raise NotImplementedError

    async def list_connected_apps(self, user_id: UUID) -> list[ConnectedApp]:
        """One entry per OAuth family with a live refresh token."""
        raise NotImplementedError

    async def revoke_family(
        self,
        family_id: UUID,
        *,
        reason: str,
        actor: CredentialActor,
        owner_id: UUID | None = None,
    ) -> None:
        """Revokes every live row of the family; writes oauth.family_revoked."""
        raise NotImplementedError

    async def list_events(
        self, *, tenant: str, user_id: UUID | None = None, limit: int = 100
    ) -> list[CredentialEvent]:
        """credential_events in `tenant`, newest first."""
        raise NotImplementedError

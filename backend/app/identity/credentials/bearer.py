"""The single bearer door (D3, D20): every PAT, service token and OAuth access token
an MCP caller presents is checked here, plus the user lookups the MCP edge needs."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.api_tokens import (
    BEARER_KINDS,
    LAST_USED_INTERVAL,
    TokenKind,
    display_prefix,
    hash_secret,
    kind_of,
)
from app.identity.clock import as_utc, utcnow
from app.identity.errors import ForbiddenError
from app.identity.models import ApiToken, User, UserKind, UserStatus
from app.identity.principal import AuthMethod, Principal
from app.identity.repository import CredentialRepository, UserRepository
from app.identity.service import to_principal
from app.identity.tokens import ExpiredTokenError, InvalidTokenError

logger = structlog.get_logger()

# The only things a rejected bearer is ever told (conventions, invariant 2).
_INVALID: Final = "invalid token"
_EXPIRED: Final = "expired"
_DISABLED: Final = "Your atlas access is disabled. Contact an admin."
_AUTH_METHOD: Final[dict[TokenKind, AuthMethod]] = {
    TokenKind.PAT: "pat",
    TokenKind.SERVICE: "service",
    TokenKind.OAUTH_ACCESS: "oauth",
}


@dataclass(frozen=True, slots=True)
class AuthenticatedBearer:
    """What the bearer door hands the MCP token verifier (C11)."""

    principal: Principal  # auth_method oauth|pat|service, token_id and client_id set
    expires_at: datetime
    audience: str | None  # OAuth: the bound audience; PAT/service: None (use current)
    display_prefix: str


async def authenticate_bearer(
    db: AsyncSession, raw: str, now: datetime | None = None
) -> AuthenticatedBearer:
    """Raises InvalidTokenError (unknown, revoked, wrong kind, refresh token, revoked
    client), its subtype ExpiredTokenError (expiry is the only fault) or
    ForbiddenError (user disabled). Never includes token material in the message."""
    moment = now or utcnow()
    candidate = raw.strip()
    kind = kind_of(candidate)  # rejected before any DB work (D3)
    if kind is None or kind not in BEARER_KINDS:  # refresh tokens are never bearers
        raise _rejected("malformed" if kind is None else "not_a_bearer", None)
    prefix = display_prefix(candidate)
    creds = CredentialRepository(db)
    row = await creds.tokens.token_by_hash(hash_secret(candidate))
    if row is None:
        raise _rejected("unknown", prefix)
    reason = _dead_reason(row, kind, moment)
    if reason is not None:
        raise _rejected(reason, prefix)
    user = _active_owner(await UserRepository(db).get(row.user_id), kind, prefix)
    if kind is TokenKind.OAUTH_ACCESS:
        await _require_live_client(creds, row, prefix)
    await _touch(creds, row, moment)
    principal = replace(
        to_principal(user, _AUTH_METHOD[kind]),
        token_id=row.id,
        client_id=row.client_id,
    )
    return AuthenticatedBearer(principal, as_utc(row.expires_at), row.audience, prefix)


def _rejected(reason: str, prefix: str | None) -> InvalidTokenError:
    """The one rejection: the reason goes to the log, never to the caller. Expiry
    of an otherwise live bearer is the one subtype (`ExpiredTokenError`), same text."""
    logger.info("identity.bearer_rejected", reason=reason, prefix=prefix)
    if reason == _EXPIRED:
        return ExpiredTokenError(_INVALID)
    return InvalidTokenError(_INVALID)


def _dead_reason(row: ApiToken, kind: TokenKind, moment: datetime) -> str | None:
    if row.kind != kind:
        return "kind_mismatch"
    if row.revoked_at is not None:
        return "revoked"
    if as_utc(row.expires_at) <= moment:
        return _EXPIRED
    return None


def _active_owner(user: User | None, kind: TokenKind, prefix: str) -> User:
    if user is None:
        raise _rejected("no_user", prefix)
    if user.status != UserStatus.ACTIVE:
        logger.info("identity.bearer_rejected", reason="user_disabled", prefix=prefix)
        raise ForbiddenError(_DISABLED, "user_disabled")
    expected = UserKind.SERVICE if kind is TokenKind.SERVICE else UserKind.HUMAN
    if user.kind != expected:
        raise _rejected("user_kind", prefix)
    return user


async def _require_live_client(
    creds: CredentialRepository, row: ApiToken, prefix: str
) -> None:
    client = (
        None if row.client_id is None else await creds.clients.client(row.client_id)
    )
    if client is None or client.revoked_at is not None:
        raise _rejected("client_revoked", prefix)


async def _touch(creds: CredentialRepository, row: ApiToken, moment: datetime) -> None:
    """last_used_at, written at most every LAST_USED_INTERVAL (D3)."""
    last = row.last_used_at
    if last is not None and moment - as_utc(last) < LAST_USED_INTERVAL:
        return
    await creds.tokens.touch_token(row.id, moment)
    await creds.commit()


async def principal_for_user(db: AsyncSession, user_id: UUID) -> Principal | None:
    """Active users only; auth_method 'service' for service accounts, 'pat' otherwise.
    Used by the MCP edge to evaluate a user's Policy (eligibility, D34)."""
    user = await UserRepository(db).get(user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        return None
    return to_principal(user, "service" if user.kind == UserKind.SERVICE else "pat")


async def tenant_of_user(db: AsyncSession, user_id: UUID) -> str | None:
    """The tenant of any user, whatever their status; None for an unknown id. Lets an
    admin clean up a disabled user's credentials (D18 hook failure)."""
    user = await UserRepository(db).get(user_id)
    return None if user is None else user.tenant

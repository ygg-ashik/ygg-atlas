"""The MCP bearer check: identity's single bearer door adapted to the SDK (D20).

`AtlasTokenVerifier` satisfies the SDK `TokenVerifier` protocol structurally. Each
call runs `identity.authenticate_bearer` on its own fresh session (the door commits
`last_used_at`, and a shared session would serve stale rows from its identity map)
and fails closed: any error is "no token", never a 500 carrying the bearer.

The carrier never holds the secret (D28): `AtlasAccessToken.token` is the display
prefix, so no repr or log line can leak the bearer.

Why a bearer failed is kept per request task (`last_bearer_rejection`) for the
failed-bearer limiter (ruling E1): only bearers the door does not recognise count,
never a real token that merely expired.
"""

import hashlib
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Final, Literal
from uuid import UUID

import structlog
from mcp.server.auth.provider import AccessToken
from pydantic import ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col, select

from app.database import get_session_factory
from app.identity import (
    TOKEN_PREFIXES,
    ApiToken,
    AuthenticatedBearer,
    InvalidTokenError,
    Principal,
    TokenKind,
    authenticate_bearer,
)

logger = structlog.get_logger()

SessionFactory = Callable[[], async_sessionmaker[AsyncSession]]

# Why the last bearer check in this request failed:
# - "unrecognised": unknown, revoked, malformed or otherwise invalid (identity's
#   InvalidTokenError). The only kind the failed-bearer limiter counts.
# - "expired": a real, unrevoked bearer past its expiry. The client must
#   re-authenticate; not evidence of guessing.
# - "unavailable": anything else: the check failed (database down) or the door
#   refused a real token's owner (disabled). Not evidence of guessing.
BearerRejection = Literal["unrecognised", "expired", "unavailable"]

_REJECTION: Final[ContextVar[BearerRejection | None]] = ContextVar(
    "atlas_bearer_rejection", default=None
)


def last_bearer_rejection() -> BearerRejection | None:
    """Why the last `verify_token` in this request task failed; None if it passed
    or none ran. The bearer middleware runs in the request's own task, so an ASGI
    wrapper around it reads the verdict of exactly this request."""
    return _REJECTION.get()


class AtlasAccessToken(AccessToken):
    """SDK carrier. `token` holds the display prefix only (D28)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    principal: Principal
    token_id: UUID


class AtlasTokenVerifier:
    """Bearer -> AtlasAccessToken through identity's door, or None (fail closed)."""

    def __init__(
        self, resource_url: str, sessions: SessionFactory = get_session_factory
    ) -> None:
        self._resource_url = resource_url
        self._sessions = sessions

    async def verify_token(self, token: str) -> AtlasAccessToken | None:
        _REJECTION.set(None)
        bearer = await self._authenticate(token)
        if bearer is None:
            return None
        principal = bearer.principal
        token_id = principal.token_id
        if token_id is None:  # the door always sets it; refuse rather than guess
            _REJECTION.set("unavailable")
            logger.error("mcp.bearer_check_failed", error="MissingTokenId")
            return None
        return AtlasAccessToken(
            token=bearer.display_prefix,
            client_id=principal.client_id or principal.auth_method,
            scopes=[],
            expires_at=int(bearer.expires_at.timestamp()),
            # OAuth: the bound audience. PAT/service: the current URL (D7).
            resource=bearer.audience or self._resource_url,
            subject=str(principal.user_id),
            principal=principal,
            token_id=token_id,
        )

    async def _authenticate(self, token: str) -> AuthenticatedBearer | None:
        """Never logs or raises with token material: the door logs the reason with
        at most the display prefix; here only the exception type is recorded."""
        try:
            async with self._sessions()() as db:
                try:
                    return await authenticate_bearer(db, token)
                except InvalidTokenError:
                    expired = await _merely_expired(db, token)
                    _REJECTION.set("expired" if expired else "unrecognised")
        except Exception as exc:  # fail closed: 401, never a 500 holding the token
            _REJECTION.set("unavailable")
            # Not logger.exception: dev tracebacks render locals (the raw bearer).
            logger.error("mcp.bearer_check_failed", error=type(exc).__name__)
        return None


async def _merely_expired(db: AsyncSession, raw: str) -> bool:
    """Whether a rejected bearer is a real, unrevoked bearer row past its expiry.

    The door raises one InvalidTokenError for every reason (by design: callers
    learn nothing), so this read tells E1's two cases apart. The digest is the
    door's own storage hash (SHA-256 hex of the stripped bearer); a drift would
    only make expired tokens count as unrecognised, and the verifier tests pin it.
    """
    candidate = raw.strip()
    if not candidate.startswith(tuple(TOKEN_PREFIXES.values())):
        return False  # malformed: no row can match, skip the read
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    row = (
        await db.execute(select(ApiToken).where(col(ApiToken.token_hash) == digest))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None or row.kind == TokenKind.OAUTH_REFRESH:
        return False
    expires_at = row.expires_at
    if expires_at.tzinfo is None:  # SQLite returns naive UTC
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)

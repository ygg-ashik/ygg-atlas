"""The MCP bearer check: identity's single bearer door adapted to the SDK (D20).

`AtlasTokenVerifier` satisfies the SDK `TokenVerifier` protocol structurally. Each
call runs `identity.authenticate_bearer` on its own fresh session (the door commits
`last_used_at`, and a shared session would serve stale rows from its identity map)
and fails closed: any error is "no token", never a 500 carrying the bearer.

The carrier never holds the secret (D28): `AtlasAccessToken.token` is the display
prefix, so no repr or log line can leak the bearer.

Why a bearer failed is kept per request task (`last_bearer_rejection`) for the
failed-bearer limiter (ruling E1): only bearers the door does not recognise count,
never a real token that merely expired. `BearerRejectionScope` bounds that verdict to
one request.
"""

from collections.abc import Callable
from contextvars import ContextVar
from typing import Final, Literal
from uuid import UUID

import structlog
from mcp.server.auth.provider import AccessToken
from pydantic import ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send

from app.database import get_session_factory
from app.identity import (
    AuthenticatedBearer,
    ExpiredTokenError,
    ForbiddenError,
    InvalidTokenError,
    Principal,
    authenticate_bearer,
)

logger = structlog.get_logger()

SessionFactory = Callable[[], async_sessionmaker[AsyncSession]]

# Why the last bearer check in this request failed:
# - "unrecognised": unknown, revoked, malformed or otherwise invalid (identity's
#   InvalidTokenError). The only kind the failed-bearer limiter counts.
# - "expired": a real, unrevoked bearer past its expiry. The client must
#   re-authenticate; not evidence of guessing.
# - "refused": a real, live bearer whose owner may not use atlas (disabled).
# - "unavailable": the check itself failed (database down).
# Only "unrecognised" is evidence of guessing.
BearerRejection = Literal["unrecognised", "expired", "refused", "unavailable"]

_REJECTION: Final[ContextVar[BearerRejection | None]] = ContextVar(
    "atlas_bearer_rejection", default=None
)


def last_bearer_rejection() -> BearerRejection | None:
    """Why the last `verify_token` in this request task failed; None if it passed
    or none ran. The bearer middleware runs in the request's own task, so an ASGI
    wrapper around it reads the verdict of exactly this request."""
    return _REJECTION.get()


def bearer_unrecognised() -> bool:
    """The failed-bearer limiter's predicate (E1): count only unrecognised bearers."""
    return _REJECTION.get() == "unrecognised"


class BearerRejectionScope:
    """Pure ASGI: clears the bearer verdict before the request and restores it after,
    so a verdict never outlives its request (several requests can share one task).
    Runs in the request's task, like the SDK's AuthenticationMiddleware inside it,
    so a wrapper outside it reads exactly this request's verdict."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        token = _REJECTION.set(None)
        try:
            await self._app(scope, receive, send)
        finally:
            _REJECTION.reset(token)


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
                except ExpiredTokenError:
                    _REJECTION.set("expired")
                except InvalidTokenError:
                    _REJECTION.set("unrecognised")
                except ForbiddenError as exc:  # a real token, its owner disabled
                    _REJECTION.set("refused")
                    logger.info("mcp.bearer_refused", reason=exc.reason)
        except Exception as exc:  # fail closed: 401, never a 500 holding the token
            _REJECTION.set("unavailable")
            # Not logger.exception: dev tracebacks render locals (the raw bearer).
            logger.error("mcp.bearer_check_failed", error=type(exc).__name__)
        return None

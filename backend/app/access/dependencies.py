"""FastAPI wiring for access: the caller's Policy, capability gates, error mapping."""

from collections.abc import Awaitable, Callable

import structlog
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.admin import AccessAdmin, Actor
from app.access.cache import shared_cache
from app.access.catalog import CAPABILITIES
from app.access.errors import AccessError, PolicyUnavailableError
from app.access.policy import Policy
from app.access.repository import AccessRepository
from app.access.service import AccessService
from app.database import get_db
from app.identity import Principal, TokenVerifier, get_principal, get_token_verifier

logger = structlog.get_logger()


def get_access_service(db: AsyncSession = Depends(get_db)) -> AccessService:
    return AccessService(AccessRepository(db), shared_cache())


async def get_policy(
    principal: Principal = Depends(get_principal),
    service: AccessService = Depends(get_access_service),
) -> Policy:
    """The caller's Policy. Unavailable means deny: the request fails with 503."""
    try:
        return await service.policy_for(principal)
    except PolicyUnavailableError:
        raise HTTPException(
            503, "The access check is unavailable right now. Try again shortly."
        ) from None


def require_capability(code: str) -> Callable[..., Awaitable[Policy]]:
    """A dependency that admits only callers whose Policy has `code` (spec §3.2)."""
    if code not in CAPABILITIES:
        msg = f"Unknown capability {code!r}"
        raise ValueError(msg)

    async def check(policy: Policy = Depends(get_policy)) -> Policy:
        if not policy.has(code):
            raise HTTPException(
                403, f"Your role doesn't include this ({code}). Ask an atlas admin."
            )
        return policy

    return check


def get_access_admin(
    db: AsyncSession = Depends(get_db),
    verifier: TokenVerifier = Depends(get_token_verifier),
) -> AccessAdmin:
    repo = AccessRepository(db)
    return AccessAdmin(repo, AccessService(repo, shared_cache()), verifier)


def get_actor(policy: Policy = Depends(get_policy)) -> Actor:
    """Capability checks happen in AccessAdmin (managers are not admins, D8)."""
    return Actor.from_policy(policy)


async def access_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Maps AccessError subclasses to their HTTP status with a plain message.

    Anything else is a bug, not an access decision: it is logged and never
    exposes `str(exc)` to the caller.
    """
    if isinstance(exc, AccessError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)
    logger.exception("access.unhandled_error")
    return JSONResponse({"detail": "Something went wrong."}, status_code=500)

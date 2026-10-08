"""FastAPI wiring for access: the caller's Policy, capability gates, error mapping."""

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.cache import shared_cache
from app.access.catalog import CAPABILITIES
from app.access.errors import AccessError, PolicyUnavailableError
from app.access.policy import Policy
from app.access.repository import AccessRepository
from app.access.service import AccessService
from app.database import get_db
from app.identity import Principal, get_principal


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


async def access_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Maps AccessError subclasses to their HTTP status with a plain message."""
    status = exc.status_code if isinstance(exc, AccessError) else 500
    return JSONResponse({"detail": str(exc)}, status_code=status)

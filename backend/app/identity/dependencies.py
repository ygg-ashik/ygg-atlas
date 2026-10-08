"""FastAPI wiring for identity. Maps identity errors to HTTP status codes."""

from functools import cache

import structlog
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.identity.errors import (
    ForbiddenError,
    IdentityUnavailableError,
    UnauthenticatedError,
)
from app.identity.firebase import FirebaseVerifier
from app.identity.principal import Principal
from app.identity.repository import UserRepository
from app.identity.service import IdentityService
from app.identity.tokens import InvalidTokenError, TokenVerifier

logger = structlog.get_logger()

_bearer = HTTPBearer(auto_error=False)
_CHALLENGE = {"WWW-Authenticate": "Bearer"}


@cache
def _firebase_verifier(project_id: str) -> FirebaseVerifier:
    return FirebaseVerifier(project_id)


def get_token_verifier(settings: Settings = Depends(get_settings)) -> TokenVerifier:
    return _firebase_verifier(settings.firebase_project_id)


def get_identity_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> IdentityService:
    return IdentityService(UserRepository(db), settings)


async def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
    verifier: TokenVerifier = Depends(get_token_verifier),
    service: IdentityService = Depends(get_identity_service),
) -> Principal:
    """The single entry point: every route that needs a caller depends on this."""
    if settings.auth_disabled:
        return await service.ensure_dev_user()
    if credentials is None:
        raise HTTPException(401, "Missing bearer token", headers=_CHALLENGE)
    try:
        token = await verifier.verify(credentials.credentials)
    except IdentityUnavailableError:
        logger.exception("identity.provider_unavailable")
        raise HTTPException(503, "Sign-in is temporarily unavailable.") from None
    except InvalidTokenError as exc:
        logger.warning("identity.token_invalid", reason=str(exc))
        raise HTTPException(
            401, "Invalid or expired token", headers=_CHALLENGE
        ) from None
    try:
        return await service.resolve_web(token)
    except UnauthenticatedError as exc:
        raise HTTPException(401, str(exc), headers=_CHALLENGE) from None
    except ForbiddenError as exc:
        raise HTTPException(403, str(exc)) from None

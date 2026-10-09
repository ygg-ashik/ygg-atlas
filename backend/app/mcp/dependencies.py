"""FastAPI wiring for the MCP credential API: service factories, error mapping and
the D34 service-token check. Routes stay thin: parse, call one of these, return."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Final
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import Policy, policy_for
from app.config import Settings, get_settings
from app.database import get_db
from app.identity import (
    AuthorizationRequestNotFoundError,
    CredentialActor,
    CredentialLimitError,
    CredentialNotFoundError,
    CredentialRuleError,
    IssuedToken,
    OAuthConfig,
    OAuthService,
    TokenService,
    UserKind,
    principal_for_user,
    tenant_of_user,
)
from app.mcp.schemas import TokenCreate

_NO_SERVICE_ACCOUNT: Final = "No such active service account."
_NOT_A_SERVICE_ACCOUNT: Final = "Service tokens are for service accounts only."
_OUTRANKS: Final = (
    "You can't mint a token for an account with more access than your own."
)
_NO_USER: Final = "No such user."
_TXN_GONE: Final = "This approval request has expired or was already used."


def get_token_service(db: AsyncSession = Depends(get_db)) -> TokenService:
    return TokenService(db)


def get_oauth_service(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> OAuthService:
    return OAuthService(db, OAuthConfig.from_settings(settings))


@contextmanager
def credential_errors() -> Generator[None]:
    """Identity's credential errors as HTTP statuses. Their messages are written for
    people and never carry token material."""
    try:
        yield
    except CredentialRuleError as exc:
        raise HTTPException(400, str(exc)) from None
    except CredentialLimitError as exc:
        raise HTTPException(409, str(exc)) from None
    except CredentialNotFoundError as exc:
        raise HTTPException(404, str(exc)) from None


def transaction_gone() -> HTTPException:
    """Unknown, expired and consumed transactions all look the same: 404, and the
    body never echoes the transaction id."""
    return HTTPException(404, _TXN_GONE)


@contextmanager
def consent_errors() -> Generator[None]:
    try:
        yield
    except AuthorizationRequestNotFoundError:
        raise transaction_gone() from None


async def require_tenant_user(db: AsyncSession, user_id: UUID, tenant: str) -> None:
    """A user in `tenant`, active or not, else 404 (no probing other tenants' ids)."""
    if await tenant_of_user(db, user_id) != tenant:
        raise HTTPException(404, _NO_USER)


async def mint_service_token(
    db: AsyncSession,
    tokens: TokenService,
    *,
    actor: Policy,
    service_user_id: UUID,
    request: TokenCreate,
    settings: Settings,
) -> IssuedToken:
    """D34: an active service account in the actor's tenant whose capabilities are a
    subset of the actor's. The caller has already checked admin:tokens."""
    principal = await principal_for_user(db, service_user_id)
    if principal is None or principal.tenant != actor.tenant:
        raise HTTPException(404, _NO_SERVICE_ACCOUNT)
    if principal.kind != UserKind.SERVICE:
        raise HTTPException(400, _NOT_A_SERVICE_ACCOUNT)
    target = await policy_for(db, principal)
    if not target.capabilities <= actor.capabilities:
        raise HTTPException(403, _OUTRANKS)
    with credential_errors():
        return await tokens.create_service_token(
            service_user_id,
            name=request.name,
            expires_in_days=request.expires_in_days,
            actor=CredentialActor(actor.user_id, "api"),
            default_days=settings.pat_default_days,
            max_days=settings.pat_max_days,
        )

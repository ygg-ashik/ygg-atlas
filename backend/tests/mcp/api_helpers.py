"""Shared helpers for the MCP credential API tests (Task 8).

The router is mounted on a bare test app (main.py mounts it in Task 6), with the
access error handler the real app registers. `as_user` swaps the Firebase door for
a fixed principal; the caller's Policy is still evaluated from the database.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import AccessError, access_error_handler
from app.config import Settings, get_settings
from app.identity import (
    AuthorizationRequestData,
    InvalidTokenError,
    OAuthService,
    Principal,
    User,
    get_principal,
    get_token_verifier,
)
from app.identity.tokens import VerifiedToken
from app.mcp.router import mcp_router
from tests.identity.credential_helpers import LOOPBACK_REDIRECT
from tests.identity.oauth_helpers import (
    auth_request,
    oauth_config,
    query_param,
    registration,
)


def api_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AccessError, access_error_handler)
    app.include_router(mcp_router)
    return app


def principal_of(user: User) -> Principal:
    return Principal(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        kind=user.kind,
        tenant=user.tenant,
        auth_method="web",
    )


def as_user(app: FastAPI, user: User) -> None:
    """Every request on `app` is now made by `user` (a Firebase-door caller)."""
    principal = principal_of(user)

    async def _principal() -> Principal:
        return principal

    app.dependency_overrides[get_principal] = _principal


@asynccontextmanager
async def client_for(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


class FakeFirebase:
    """A Firebase verifier that accepts the bearer "good" for one Google account."""

    def __init__(self, email: str, uid: str = "fb-test") -> None:
        self.email = email
        self.uid = uid

    async def verify(self, token: str) -> VerifiedToken:
        if token != "good":  # a test bearer, not a secret
            raise InvalidTokenError("bad")
        return VerifiedToken(
            uid=self.uid,
            email=self.email,
            email_verified=True,
            name="Test",
            auth_time=int(datetime.now(UTC).timestamp()),
            sign_in_provider="google.com",
        )

    async def revoke(self, firebase_uid: str) -> None:
        return None


def real_door(app: FastAPI, firebase: FakeFirebase | None = None) -> None:
    """The real get_principal with AUTH_DISABLED off (conftest turns it on), behind
    a fake Firebase. Without `firebase`, any verification fails."""
    app.dependency_overrides.pop(get_principal, None)
    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(
        {"environment": "test", "auth_disabled": False}
    )
    verifier = firebase or FakeFirebase("nobody@yougotagift.com")
    app.dependency_overrides[get_token_verifier] = lambda: verifier


def oauth_service(db: AsyncSession) -> OAuthService:
    """The service as the router builds it under the default ATLAS_PUBLIC_URL."""
    return OAuthService(db, oauth_config())


async def start_authorization(
    db: AsyncSession,
    *,
    redirect: str = LOOPBACK_REDIRECT,
    name: str | None = "Claude Code",
    request: AuthorizationRequestData | None = None,
) -> tuple[str, str]:
    """Registers a public client and begins an authorization: (client_id, raw txn)."""
    service = oauth_service(db)
    reg = registration(redirect_uris=(redirect,), name=name)
    await service.register_client(reg)
    consent_url = await service.begin_authorization(
        reg.client_id, request or auth_request(redirect)
    )
    return reg.client_id, query_param(consent_url, "txn")

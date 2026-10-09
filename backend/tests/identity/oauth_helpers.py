"""Shared helpers for OAuth service tests: config, PKCE, a settable clock, and
one-call setups that run the real service (register, consent, exchange)."""

import base64
import hashlib
import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from app.identity.models import User
from app.identity.oauth import (
    AuthorizationRequestData,
    ClientRegistration,
    CodeGrant,
    OAuthConfig,
    OAuthService,
    TokenPair,
)
from tests.identity.credential_helpers import LOOPBACK_REDIRECT

PUBLIC_URL = "http://localhost:8080"
RESOURCE = f"{PUBLIC_URL}/mcp-server/mcp"
HOSTED_REDIRECT = "https://claude.ai/api/mcp/auth_callback"
GRANT_TYPES = ("authorization_code", "refresh_token")


class Clock:
    """A settable clock for OAuthService; starts at the real time so rows written
    directly by other helpers line up with it."""

    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def oauth_config(**overrides: Any) -> OAuthConfig:
    base = OAuthConfig(
        issuer=f"{PUBLIC_URL}/mcp-server",
        resource=RESOURCE,
        consent_url=f"{PUBLIC_URL}/oauth/consent",
        hosted_redirect_uris=frozenset({HOSTED_REDIRECT}),
    )
    return replace(base, **overrides)


def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge) as RFC 7636 §4.2 defines them."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def registration(
    *,
    redirect_uris: tuple[str, ...] = (LOOPBACK_REDIRECT,),
    client_secret: str | None = None,
    auth_method: str = "none",
    name: str | None = "Claude Code",
    grant_types: tuple[str, ...] = GRANT_TYPES,
    response_types: tuple[str, ...] = ("code",),
) -> ClientRegistration:
    return ClientRegistration(
        client_id=f"client-{uuid4()}",
        client_secret=client_secret,
        client_name=name,
        redirect_uris=redirect_uris,
        token_endpoint_auth_method=auth_method,
        grant_types=grant_types,
        response_types=response_types,
        software_id="claude-code",
    )


async def register_public_client(
    service: OAuthService, redirect: str = LOOPBACK_REDIRECT
) -> str:
    reg = registration(redirect_uris=(redirect,))
    await service.register_client(reg)
    return reg.client_id


def auth_request(
    redirect: str = LOOPBACK_REDIRECT,
    *,
    challenge: str | None = None,
    state: str | None = "state-123",
    resource: str | None = RESOURCE,
) -> AuthorizationRequestData:
    return AuthorizationRequestData(
        redirect_uri=redirect,
        redirect_uri_provided_explicitly=True,
        code_challenge=challenge if challenge is not None else pkce_pair()[1],
        state=state,
        scopes=(),
        resource=resource,
    )


def query_param(url: str, name: str) -> str:
    values = parse_qs(urlsplit(url).query).get(name)
    assert values, f"{name} missing from the redirect"
    return values[0]


async def begin(service: OAuthService, client_id: str) -> str:
    """Starts an authorization and returns its raw txn."""
    consent_url = await service.begin_authorization(client_id, auth_request())
    return query_param(consent_url, "txn")


async def approved_code(
    service: OAuthService, user: User, client_id: str
) -> tuple[str, CodeGrant]:
    """Runs begin -> approve and returns (raw code, loaded grant)."""
    redirect = await service.approve(await begin(service, client_id), user.id)
    raw = query_param(redirect, "code")
    grant = await service.load_code(client_id, raw)
    assert grant is not None
    return raw, grant


async def issued_pair(service: OAuthService, user: User, client_id: str) -> TokenPair:
    _, grant = await approved_code(service, user, client_id)
    return await service.exchange_code(client_id, grant, always_eligible)


async def always_eligible(_user_id: UUID) -> bool:
    return True


async def never_eligible(_user_id: UUID) -> bool:
    return False

"""The OAuth 2.1 authorization service behind the MCP edge (D4-D8, D30, D36).

Interface first (D35): auth phase 4 Task 2 lands these signatures so the MCP SDK
adapters and the consent API can code against them; Task 4 fills the bodies. It never
imports `credentials` (a sibling layer) or the MCP SDK.
"""

from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, Self
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.identity.api_tokens import (
    ACCESS_TOKEN_TTL,
    AUTHORIZATION_REQUEST_TTL,
    CODE_TTL,
    REFRESH_REUSE_GRACE,
    REFRESH_TOKEN_TTL,
    CredentialActor,
)

INVALID_REQUEST: Final = "invalid_request"
INVALID_GRANT: Final = "invalid_grant"
RegistrationErrorCode = Literal["invalid_redirect_uri", "invalid_client_metadata"]

# Supplied by app/mcp: the user is active and holds mcp:use.
Eligibility = Callable[[UUID], Awaitable[bool]]


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class OAuthConfig:
    issuer: str
    resource: str
    consent_url: str
    hosted_redirect_uris: frozenset[str]
    access_ttl: timedelta = ACCESS_TOKEN_TTL
    refresh_ttl: timedelta = REFRESH_TOKEN_TTL
    code_ttl: timedelta = CODE_TTL
    request_ttl: timedelta = AUTHORIZATION_REQUEST_TTL
    refresh_grace: timedelta = REFRESH_REUSE_GRACE

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """Issuer, resource and consent URLs from ATLAS_PUBLIC_URL (D2)."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ClientRegistration:
    """What dynamic client registration hands us (mapped from the SDK by app/mcp)."""

    client_id: str
    client_secret: str | None = field(repr=False)
    client_name: str | None
    redirect_uris: tuple[str, ...]
    token_endpoint_auth_method: str
    grant_types: tuple[str, ...]
    response_types: tuple[str, ...]
    software_id: str | None


@dataclass(frozen=True, slots=True)
class RegisteredClient:
    """A live client. The secret hash never leaves identity except to authenticate."""

    client_id: str
    client_name: str | None
    redirect_uris: tuple[str, ...]
    token_endpoint_auth_method: str
    grant_types: tuple[str, ...]
    response_types: tuple[str, ...]
    registered_at: datetime
    secret_hash: str | None = field(default=None, repr=False)

    def secret_matches(self, presented: str | None) -> bool:
        """hmac.compare_digest on hashes; a public client matches only no secret."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class AuthorizationRequestData:
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    state: str | None
    scopes: tuple[str, ...]
    resource: str | None


@dataclass(frozen=True, slots=True)
class PendingAuthorization:
    """What the consent page shows about a pending request."""

    client_id: str
    client_name: str | None
    redirect_uri: str
    redirect_host: str
    loopback: bool
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CodeGrant:
    code_id: UUID
    family_id: UUID
    client_id: str
    user_id: UUID
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    resource: str
    scopes: tuple[str, ...]
    expires_at: datetime
    display: str  # display prefix only (D28)


@dataclass(frozen=True, slots=True)
class RefreshGrant:
    token_id: UUID
    family_id: UUID
    client_id: str
    user_id: UUID
    resource: str
    expires_at: datetime
    display: str  # display prefix only (D28)


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int
    family_id: UUID
    user_id: UUID


@dataclass(frozen=True, slots=True)
class ClientSummary:
    """One row of /admin/clients."""

    client_id: str
    client_name: str | None
    redirect_uris: tuple[str, ...]
    token_endpoint_auth_method: str
    registered_at: datetime
    revoked_at: datetime | None
    active_families: int


@dataclass(frozen=True, slots=True)
class GcReport:
    codes: int
    requests: int
    tokens: int
    clients: int


class OAuthRegistrationError(Exception):
    """Dynamic registration refused (RFC 7591 error codes)."""

    def __init__(self, error: RegistrationErrorCode, description: str) -> None:
        super().__init__(description)
        self.error: RegistrationErrorCode = error
        self.description = description


class OAuthRequestError(Exception):
    """An /authorize request refused; `description` is safe to show."""

    error: Final = INVALID_REQUEST

    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = description


class OAuthGrantError(Exception):
    """A code or refresh grant refused; `description` is safe to show."""

    error: Final = INVALID_GRANT

    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = description


class AuthorizationRequestNotFoundError(Exception):
    """Unknown, expired or already consumed authorization request (404)."""


def canonical_resource(url: str) -> str | None:
    """The SDK's own comparison (BearerAuthBackend._issued_for_this_resource): case and
    default port do not matter, one trailing slash aside. None if not a URL."""
    raise NotImplementedError


def redirect_allowed(uri: str, hosted: Collection[str]) -> bool:
    """D8. Parsed with Pydantic AnyUrl (WHATWG, as the browser parses it): loopback
    http on any port and path, or an exact approved https callback."""
    raise NotImplementedError


def is_loopback_redirect(uri: str) -> bool:
    """True for an http redirect to localhost, 127.0.0.1 or [::1]."""
    raise NotImplementedError


def with_query(uri: str, **params: str | None) -> str:
    """`uri` with `params` added to its query; keeps the existing query, skips None."""
    raise NotImplementedError


class OAuthService:
    """Clients, consent, codes and token families. One instance per request."""

    def __init__(
        self,
        db: AsyncSession,
        config: OAuthConfig,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        raise NotImplementedError

    async def register_client(self, registration: ClientRegistration) -> None:
        """Validates and stores a DCR client (secret hashed); writes
        client.registered. Raises OAuthRegistrationError."""
        raise NotImplementedError

    async def get_client(self, client_id: str) -> RegisteredClient | None:
        """None for unknown or revoked clients, or when no stored redirect is still
        allowed."""
        raise NotImplementedError

    async def begin_authorization(
        self, client_id: str, request: AuthorizationRequestData
    ) -> str:
        """Stores the request under hash(txn) and returns the consent URL with txn.
        Raises OAuthRequestError."""
        raise NotImplementedError

    async def pending_request(self, txn: str) -> PendingAuthorization | None:
        raise NotImplementedError

    async def approve(self, txn: str, user_id: UUID) -> str:
        """Consumes the request once and returns the redirect carrying a code bound
        to `user_id`. Raises AuthorizationRequestNotFoundError."""
        raise NotImplementedError

    async def deny(self, txn: str, user_id: UUID) -> str:
        """Consumes the request and returns the access_denied redirect."""
        raise NotImplementedError

    async def load_code(self, client_id: str, raw_code: str) -> CodeGrant | None:
        """None for unknown, foreign or reused codes (reuse revokes the family)."""
        raise NotImplementedError

    async def exchange_code(
        self, client_id: str, grant: CodeGrant, eligible: Eligibility
    ) -> TokenPair:
        """Exactly one exchange of a code succeeds (D30). Raises OAuthGrantError."""
        raise NotImplementedError

    async def load_refresh(
        self, client_id: str, raw_refresh: str
    ) -> RefreshGrant | None:
        """None for non-refresh or unknown tokens; a cross-client presentation revokes
        the family."""
        raise NotImplementedError

    async def rotate_refresh(
        self, client_id: str, grant: RefreshGrant, eligible: Eligibility
    ) -> TokenPair:
        """Rotation with reuse detection and a 30 s same-client grace (D6). Raises
        OAuthGrantError."""
        raise NotImplementedError

    async def revoke_by_token_id(self, token_id: UUID) -> None:
        """RFC 7009: revokes the token's whole family."""
        raise NotImplementedError

    async def revoke_client(self, client_id: str, *, actor: CredentialActor) -> bool:
        """Revokes the client and all its tokens; writes client.revoked."""
        raise NotImplementedError

    async def list_clients(self) -> list[ClientSummary]:
        raise NotImplementedError

    async def gc(self) -> GcReport:
        """delete_stale, then a credentials.gc event with the counts."""
        raise NotImplementedError

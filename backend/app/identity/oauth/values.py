"""The values the OAuth service takes and returns (mapped to the SDK by app/mcp).

Raw secrets appear only in the fields marked `repr=False`, never in a repr.
"""

import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from app.identity.api_tokens import hash_secret
from app.identity.repository import GcCounts

PUBLIC_METHOD: Final = "none"

# Supplied by app/mcp: True when the user is active and holds mcp:use, False when
# not. It raises EligibilityUnavailableError when it could not check; any other
# exception is treated the same way.
Eligibility = Callable[[UUID], Awaitable[bool]]
ReuseKind = Literal["code", "refresh"]

# What `OAuthService.gc` removed: the repository's counts are the report.
GcReport = GcCounts


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
        """The auth method decides: a public client authenticates with no secret (a
        presented one is ignored); a confidential one only with its own, compared
        as hashes in constant time. A confidential client with no hash never does."""
        if self.token_endpoint_auth_method == PUBLIC_METHOD:
            return True
        if self.secret_hash is None or presented is None:
            return False
        return hmac.compare_digest(self.secret_hash, hash_secret(presented))


@dataclass(frozen=True, slots=True)
class ClientSummary:
    """One row of /admin/clients."""

    client_id: str
    client_name: str  # UNNAMED_CLIENT when the client registered none
    redirect_uris: tuple[str, ...]
    token_endpoint_auth_method: str
    registered_at: datetime
    revoked_at: datetime | None
    active_families: int


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
    client_name: str  # UNNAMED_CLIENT when the client registered none
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
    display: str  # display prefix only


@dataclass(frozen=True, slots=True)
class RefreshGrant:
    token_id: UUID
    family_id: UUID
    client_id: str
    user_id: UUID
    resource: str
    expires_at: datetime
    display: str  # display prefix only


@dataclass(frozen=True, slots=True)
class AccessTokenRef:
    """An OAuth access token as RFC 7009 revocation needs it: whose it is."""

    token_id: UUID
    client_id: str


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int
    family_id: UUID
    user_id: UUID

"""The OAuth 2.1 authorization service behind the MCP edge (D4-D8, D30, D36).

Clients (dynamic registration, allowlisted redirects), pending authorizations,
single-use codes and rotating refresh-token families with reuse detection, one
file per step. Only hashes are stored; raw codes, txn ids, tokens and client
secrets live in the request and the response alone. It never imports
`credentials` (a sibling layer) or the MCP SDK: `app/mcp` adapts `OAuthService`
to the SDK handlers.
"""

from app.identity.oauth.config import OAuthConfig
from app.identity.oauth.errors import (
    INVALID_GRANT,
    INVALID_REQUEST,
    AuthorizationRequestNotFoundError,
    EligibilityUnavailableError,
    GrantUnavailableError,
    OAuthGrantError,
    OAuthRegistrationError,
    OAuthRequestError,
    RegistrationErrorCode,
)
from app.identity.oauth.service import OAuthService
from app.identity.oauth.urls import (
    canonical_resource,
    is_loopback_redirect,
    redirect_allowed,
    with_query,
)
from app.identity.oauth.values import (
    AccessTokenRef,
    AuthorizationRequestData,
    ClientRegistration,
    ClientSummary,
    CodeGrant,
    Eligibility,
    GcReport,
    PendingAuthorization,
    RefreshGrant,
    RegisteredClient,
    ReuseKind,
    TokenPair,
)

__all__ = [
    "INVALID_GRANT",
    "INVALID_REQUEST",
    "AccessTokenRef",
    "AuthorizationRequestData",
    "AuthorizationRequestNotFoundError",
    "ClientRegistration",
    "ClientSummary",
    "CodeGrant",
    "Eligibility",
    "EligibilityUnavailableError",
    "GcReport",
    "GrantUnavailableError",
    "OAuthConfig",
    "OAuthGrantError",
    "OAuthRegistrationError",
    "OAuthRequestError",
    "OAuthService",
    "PendingAuthorization",
    "RefreshGrant",
    "RegisteredClient",
    "RegistrationErrorCode",
    "ReuseKind",
    "TokenPair",
    "canonical_resource",
    "is_loopback_redirect",
    "redirect_allowed",
    "with_query",
]

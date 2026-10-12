"""Where the OAuth service runs and how long what it issues lives."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Self

from app.config import Settings
from app.identity.api_tokens import (
    ACCESS_TOKEN_TTL,
    AUTHORIZATION_REQUEST_TTL,
    CODE_TTL,
    REFRESH_REUSE_GRACE,
    REFRESH_TOKEN_TTL,
)


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
        return cls(
            issuer=settings.mcp_issuer_url,
            resource=settings.mcp_resource_url,
            consent_url=settings.oauth_consent_url,
            hosted_redirect_uris=frozenset(settings.hosted_redirect_uri_list),
        )

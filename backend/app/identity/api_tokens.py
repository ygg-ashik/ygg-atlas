"""Token kinds, lifetimes and the pure functions that mint, hash and classify secrets.

No I/O and no models: every credential service builds on this module. Raw secrets are
256-bit `secrets.token_urlsafe` values; only `hash_secret(raw)` is ever persisted (D3).
"""

import hashlib
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal
from uuid import UUID


class TokenKind(StrEnum):
    PAT = "pat"
    SERVICE = "service"
    OAUTH_ACCESS = "oauth_access"
    OAUTH_REFRESH = "oauth_refresh"


TOKEN_PREFIXES: Final[Mapping[TokenKind, str]] = MappingProxyType(
    {
        TokenKind.PAT: "atl_pat_",
        TokenKind.SERVICE: "atl_svc_",
        TokenKind.OAUTH_ACCESS: "atl_oat_",
        TokenKind.OAUTH_REFRESH: "atl_ort_",
    }
)
# Kinds accepted as an `Authorization: Bearer` credential. Refresh tokens never are.
BEARER_KINDS: Final = frozenset(
    {TokenKind.PAT, TokenKind.SERVICE, TokenKind.OAUTH_ACCESS}
)

SECRET_BYTES: Final = 32  # 256-bit; token_urlsafe(32) is 43 chars
DISPLAY_PREFIX_LENGTH: Final = 14

ACCESS_TOKEN_TTL: Final = timedelta(hours=1)
REFRESH_TOKEN_TTL: Final = timedelta(days=30)
CODE_TTL: Final = timedelta(seconds=60)
AUTHORIZATION_REQUEST_TTL: Final = timedelta(minutes=10)
REFRESH_REUSE_GRACE: Final = timedelta(seconds=30)
LAST_USED_INTERVAL: Final = timedelta(minutes=5)
CLIENT_IDLE_GC: Final = timedelta(days=90)
MAX_LIVE_PATS: Final = 10
MAX_TOKEN_DAYS: Final = 365
# The display name of an OAuth client that registered none.
UNNAMED_CLIENT: Final = "Unnamed client"

# api_tokens.revoked_reason values (varchar 32)
REVOKED_ROTATED: Final = "rotated"
REVOKED_BY_USER: Final = "user_revoked"
REVOKED_BY_ADMIN: Final = "admin_revoked"
REVOKED_USER_DISABLED: Final = "user_disabled"
REVOKED_CLIENT: Final = "client_revoked"
REVOKED_APP_DISCONNECTED: Final = "app_disconnected"
REVOKED_CODE_REUSE: Final = "code_reuse"
REVOKED_REFRESH_REUSE: Final = "refresh_reuse"
REVOKED_CROSS_CLIENT: Final = "cross_client"
REVOKED_AUDIENCE_CHANGED: Final = "audience_changed"
REVOKED_NO_MCP_USE: Final = "no_mcp_use"
REVOKED_OAUTH_REVOKE: Final = "oauth_revoke"

# credential_events.event values (varchar 48)
# Event names, not secrets (S105 matches the word "token").
EVENT_TOKEN_CREATED: Final = "token.created"  # noqa: S105
EVENT_TOKEN_REVOKED: Final = "token.revoked"  # noqa: S105
EVENT_TOKENS_REVOKED_ALL: Final = "tokens.revoked_all"
EVENT_CLIENT_REGISTERED: Final = "client.registered"
EVENT_CLIENT_REVOKED: Final = "client.revoked"
EVENT_CONSENT_APPROVED: Final = "consent.approved"
EVENT_CONSENT_DENIED: Final = "consent.denied"
EVENT_TOKENS_ISSUED: Final = "oauth.tokens_issued"
EVENT_REFRESHED: Final = "oauth.refreshed"
EVENT_REFRESH_GRACE: Final = "oauth.refresh_grace"
EVENT_REUSE_DETECTED: Final = "oauth.reuse_detected"
EVENT_FAMILY_REVOKED: Final = "oauth.family_revoked"
EVENT_GC: Final = "credentials.gc"

CredentialVia = Literal["api", "cli", "oauth", "system"]


@dataclass(frozen=True, slots=True)
class CredentialActor:
    """Who changed a credential, as recorded in credential_events."""

    user_id: UUID | None
    via: CredentialVia


_SECRET_BODY: Final = re.compile(r"[A-Za-z0-9_-]{43}")


def mint(kind: TokenKind) -> str:
    """A new raw token of `kind`. Shown once; persist only `hash_secret(raw)`."""
    return TOKEN_PREFIXES[kind] + secrets.token_urlsafe(SECRET_BYTES)


def mint_secret() -> str:
    """A new unprefixed 256-bit secret for codes and authorization-request ids."""
    return secrets.token_urlsafe(SECRET_BYTES)


def hash_secret(raw: str) -> str:
    """The SHA-256 hex digest stored in place of a raw secret."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def kind_of(raw: str) -> TokenKind | None:
    """The kind a raw bearer claims, or None. Checked before any DB lookup (D3)."""
    for kind, prefix in TOKEN_PREFIXES.items():
        if raw.startswith(prefix) and _SECRET_BODY.fullmatch(raw[len(prefix) :]):
            return kind
    return None


def display_prefix(raw: str) -> str:
    """The part of a secret that UIs and logs may show; never enough to use it."""
    return raw[:DISPLAY_PREFIX_LENGTH] if kind_of(raw) else raw[:6]

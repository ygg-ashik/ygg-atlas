"""Request and response shapes of the MCP credential API (phase 4 analysis §4).

Binding for phase 5's admin and account UI. A raw token appears only in
`TokenCreatedOut`, the response to a create; no list shape carries one.
"""

from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

UNNAMED_CLIENT: Final = "Unnamed client"
_TOKEN_NAME_MAX: Final = 100
_TOKEN_DAYS_MAX: Final = 365
_SERVICE_NAME_MIN, _SERVICE_NAME_MAX = 3, 60
_TXN_MIN, _TXN_MAX = 20, 100

AdminTokenKind = Literal["pat", "service", "oauth"]
# Why a caller cannot approve a consent: `ConsentPromptOut.ineligible_reason` and the
# `detail.reason` of every consent 403. The page switches on these, never on text.
ConsentRefusal = Literal[
    "no_mcp_use", "user_disabled", "not_company_account", "service_account"
]


class TokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    name: str
    prefix: str  # the 14-char display prefix, never the secret
    user_id: UUID
    client_id: str | None
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    revoked_reason: str | None


class TokenCreatedOut(TokenOut):
    token: str  # shown once; never in any list response


class TokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=_TOKEN_NAME_MAX)
    expires_in_days: int | None = Field(default=None, ge=1, le=_TOKEN_DAYS_MAX)


class ConnectedAppOut(BaseModel):
    family_id: UUID
    client_id: str
    client_name: str
    redirect_host: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime


class ClientOut(BaseModel):
    client_id: str
    client_name: str
    redirect_uris: list[str]
    token_endpoint_auth_method: str
    registered_at: datetime
    revoked_at: datetime | None
    active_families: int


class ConsentPromptOut(BaseModel):
    transaction_id: str
    client_name: str
    redirect_uri: str
    redirect_host: str
    loopback: bool
    user_email: str
    eligible: bool
    ineligible_reason: ConsentRefusal | None
    expires_at: datetime


class ConsentDecision(BaseModel):
    # Nothing else in the body can steer the grant: client, redirect, PKCE and
    # audience come from the stored request, the user from the bearer (D36).
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=_TXN_MIN, max_length=_TXN_MAX)
    decision: Literal["approve", "deny"]


class ConsentOut(BaseModel):
    redirect_to: str


class ConsentRefusalOut(BaseModel):
    """The `detail` of a consent 403."""

    reason: ConsentRefusal
    message: str


class ServiceAccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=_SERVICE_NAME_MIN, max_length=_SERVICE_NAME_MAX)
    role: str


class ServiceAccountOut(BaseModel):
    """access.UserOut's fields plus the owner (phase-5 compatible)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    kind: str
    role: str
    status: str
    last_seen_at: datetime | None
    owner_user_id: UUID | None


class RevokedOut(BaseModel):
    revoked: int


class CredentialEventOut(BaseModel):
    """One credential_events row. `user_id` is None for events about no user
    (client registration, garbage collection): those are global and listed with
    every tenant's events."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    at: datetime
    event: str
    user_id: UUID | None
    actor_user_id: UUID | None
    via: str
    token_id: UUID | None
    client_id: str | None
    details: dict[str, Any]


class PatMethodOut(BaseModel):
    enabled: bool
    default_days: int
    max_days: int


class OAuthMethodOut(BaseModel):
    enabled: bool
    hosted_connectors: bool


class AuthMethodsOut(BaseModel):
    pat: PatMethodOut
    oauth: OAuthMethodOut

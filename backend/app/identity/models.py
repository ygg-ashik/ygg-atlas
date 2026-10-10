"""Identity tables (spec §7): users, and the credentials that act as them (phase 4).

Credential rows hold only `hash_secret(raw)` and a display prefix, never a raw secret.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, TIMESTAMP, CheckConstraint, Column, Index
from sqlmodel import Field, SQLModel

DEFAULT_ROLE = "viewer"
DEFAULT_TENANT = "ygg"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class UserKind(StrEnum):
    HUMAN = "human"
    SERVICE = "service"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    __tablename__ = "users"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=320)
    firebase_uid: str | None = Field(
        default=None, unique=True, index=True, max_length=128
    )
    display_name: str = Field(default="", max_length=200)
    status: str = Field(default=UserStatus.ACTIVE, max_length=16)
    kind: str = Field(default=UserKind.HUMAN, max_length=16)
    role: str = Field(default=DEFAULT_ROLE, max_length=32)
    owner_user_id: UUID | None = Field(default=None, foreign_key="users.id")
    tenant: str = Field(default=DEFAULT_TENANT, max_length=64)
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )
    last_seen_at: datetime | None = Field(
        default=None, sa_type=TIMESTAMP(timezone=True)
    )


class OAuthClient(SQLModel, table=True):
    """A dynamically registered OAuth client (D8). Secrets are stored hashed."""

    __tablename__ = "oauth_clients"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    client_id: str = Field(primary_key=True, max_length=255)
    client_name: str | None = Field(default=None, max_length=100)
    redirect_uris: list[str] = Field(sa_column=Column(JSON, nullable=False))
    # none | client_secret_post | client_secret_basic
    token_endpoint_auth_method: str = Field(max_length=32)
    client_secret_hash: str | None = Field(default=None, max_length=64)
    grant_types: list[str] = Field(sa_column=Column(JSON, nullable=False))
    response_types: list[str] = Field(sa_column=Column(JSON, nullable=False))
    software_id: str | None = Field(default=None, max_length=200)
    registered_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )
    last_used_at: datetime | None = Field(
        default=None, sa_type=TIMESTAMP(timezone=True)
    )
    revoked_at: datetime | None = Field(default=None, sa_type=TIMESTAMP(timezone=True))


class ApiToken(SQLModel, table=True):
    """Every bearer and refresh credential: PATs, service tokens and OAuth tokens (D3).

    OAuth rows carry `client_id`, `family_id` (one per consent) and `audience` (D7).
    """

    __tablename__ = "api_tokens"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr
    __table_args__ = (
        Index("ix_api_tokens_user_id_kind", "user_id", "kind"),
        CheckConstraint(
            "kind IN ('pat', 'service', 'oauth_access', 'oauth_refresh')",
            name="ck_api_tokens_kind",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    kind: str = Field(max_length=16)
    token_hash: str = Field(max_length=64, unique=True, index=True)
    prefix: str = Field(max_length=16)
    name: str = Field(default="", max_length=100)
    client_id: str | None = Field(
        default=None, foreign_key="oauth_clients.client_id", index=True, max_length=255
    )
    family_id: UUID | None = Field(default=None, index=True)
    audience: str | None = Field(default=None, max_length=500)
    created_by: UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )
    expires_at: datetime = Field(sa_type=TIMESTAMP(timezone=True))
    last_used_at: datetime | None = Field(
        default=None, sa_type=TIMESTAMP(timezone=True)
    )
    revoked_at: datetime | None = Field(default=None, sa_type=TIMESTAMP(timezone=True))
    revoked_reason: str | None = Field(default=None, max_length=32)


class OAuthAuthorizationRequest(SQLModel, table=True):
    """A pending /authorize request awaiting consent. `id` is hash_secret(txn) (D36)."""

    __tablename__ = "oauth_authorization_requests"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    id: str = Field(primary_key=True, max_length=64)
    client_id: str = Field(
        foreign_key="oauth_clients.client_id", index=True, max_length=255
    )
    redirect_uri: str = Field(max_length=2000)
    redirect_uri_provided_explicitly: bool
    code_challenge: str = Field(max_length=128)
    state: str | None = Field(default=None, max_length=500)
    scopes: list[str] = Field(sa_column=Column(JSON, nullable=False))
    resource: str = Field(max_length=500)  # the bound audience (D7)
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )
    expires_at: datetime = Field(sa_type=TIMESTAMP(timezone=True))
    consumed_at: datetime | None = Field(default=None, sa_type=TIMESTAMP(timezone=True))


class OAuthCode(SQLModel, table=True):
    """A single-use authorization code (D5), bound to its client, user and family."""

    __tablename__ = "oauth_codes"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    code_hash: str = Field(max_length=64, unique=True, index=True)
    client_id: str = Field(
        foreign_key="oauth_clients.client_id", index=True, max_length=255
    )
    user_id: UUID = Field(foreign_key="users.id", index=True)
    family_id: UUID
    code_challenge: str = Field(max_length=128)
    redirect_uri: str = Field(max_length=2000)
    redirect_uri_provided_explicitly: bool
    resource: str = Field(max_length=500)
    scopes: list[str] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )
    expires_at: datetime = Field(sa_type=TIMESTAMP(timezone=True))
    used_at: datetime | None = Field(default=None, sa_type=TIMESTAMP(timezone=True))


class CredentialEvent(SQLModel, table=True):
    """Append-only credential log (D15). token_id/client_id are plain columns: the log
    outlives garbage-collected rows."""

    __tablename__ = "credential_events"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True), index=True
    )
    event: str = Field(max_length=48)
    user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    actor_user_id: UUID | None = Field(default=None, foreign_key="users.id")
    via: str = Field(max_length=16)
    token_id: UUID | None = None
    client_id: str | None = Field(default=None, max_length=255)
    details: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

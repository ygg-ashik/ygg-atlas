"""The users table: one row per human or service identity (spec §7)."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import TIMESTAMP
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

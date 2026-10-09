"""Access-control tables (spec §7). Row scopes and clearances arrive in phase 3."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    BigInteger,
    CheckConstraint,
    Column,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.access.facts import DEFAULT_TENANT, STANDING_MEMBER


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Capability(SQLModel, table=True):
    """Mirror of the code catalog (app.access.catalog), synced at startup."""

    __tablename__ = "capabilities"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    code: str = Field(primary_key=True, max_length=64)
    description: str = Field(max_length=200)
    deprecated: bool = False


class Group(SQLModel, table=True):
    __tablename__ = "groups"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr
    __table_args__ = (UniqueConstraint("tenant", "name", name="uq_groups_tenant_name"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=100)
    description: str = Field(default="", max_length=500)
    parent_id: UUID | None = Field(default=None, foreign_key="groups.id", index=True)
    tenant: str = Field(default=DEFAULT_TENANT, max_length=64)
    created_by: UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )


class GroupMember(SQLModel, table=True):
    __tablename__ = "group_members"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr
    __table_args__ = (
        CheckConstraint(
            "standing IN ('member', 'manager')", name="ck_group_members_standing"
        ),
    )

    group_id: UUID = Field(foreign_key="groups.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True, index=True)
    standing: str = Field(default=STANDING_MEMBER, max_length=16)
    added_by: UUID | None = Field(default=None, foreign_key="users.id")
    added_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )


class Grant(SQLModel, table=True):
    __tablename__ = "grants"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr
    # Malformed grants fail closed in the evaluator; these keep them out entirely.
    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('group', 'user')", name="ck_grants_subject_type"
        ),
        CheckConstraint("effect IN ('allow', 'deny')", name="ck_grants_effect"),
        CheckConstraint(
            "target_kind IN ('resource', 'capability', 'clearance')",
            name="ck_grants_target_kind",
        ),
        UniqueConstraint(
            "subject_type",
            "subject_id",
            "effect",
            "target_kind",
            "target",
            name="uq_grants_subject_target",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    subject_type: str = Field(max_length=16)
    subject_id: UUID = Field(index=True)
    effect: str = Field(max_length=16)
    target_kind: str = Field(max_length=16)
    target: str = Field(max_length=200)
    reason: str = Field(default="", max_length=500)
    expires_at: datetime | None = Field(default=None, sa_type=TIMESTAMP(timezone=True))
    created_by: UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )


class RbacChange(SQLModel, table=True):
    """Append-only record of every access change (spec §9)."""

    __tablename__ = "rbac_changes"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    actor_user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    via: str = Field(default="api", max_length=16)  # 'api' | 'cli' | 'bootstrap'
    tenant: str = Field(default=DEFAULT_TENANT, max_length=64, index=True)
    action: str = Field(max_length=64)
    object_type: str = Field(max_length=32)
    object_id: str = Field(max_length=100)
    before: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    after: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True), index=True
    )


class PolicyState(SQLModel, table=True):
    """Single row. Every access write increments policy_version (spec §8)."""

    __tablename__ = "policy_state"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr
    __table_args__ = (CheckConstraint("id = 1", name="ck_policy_state_singleton"),)

    id: int = Field(
        default=1, primary_key=True, sa_column_kwargs={"autoincrement": False}
    )
    policy_version: int = Field(default=1, sa_type=BigInteger)
    updated_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )

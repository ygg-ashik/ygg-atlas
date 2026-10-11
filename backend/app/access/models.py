"""Access-control tables (spec §7): groups, grants (with row scopes), user
attributes for `$self`, label-class mask settings and the scope-dimension mirror."""

from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    BigInteger,
    CheckConstraint,
    Column,
    Index,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, SQLModel, col

from app.access.facts import DEFAULT_TENANT, STANDING_MEMBER
from app.models.audit import AtlasAuditLog


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
    # None = all rows; else {dimension: [values]} (spec §5.5). Kept last (K2).
    row_scope: dict[str, list[str]] | None = Field(default=None, sa_column=Column(JSON))


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


class UserAttribute(SQLModel, table=True):
    """Admin-set attribute that `$self` in a row scope resolves to (D3.5)."""

    __tablename__ = "user_attributes"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    key: str = Field(primary_key=True, max_length=64)
    value: str = Field(max_length=200)
    set_by: UUID | None = Field(default=None, foreign_key="users.id")
    set_at: datetime = Field(default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True))


class LabelClassSetting(SQLModel, table=True):
    """How a breakdown label class is shown without its clearance (spec §5.6)."""

    __tablename__ = "label_class_settings"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr
    __table_args__ = (
        CheckConstraint(
            "mode IN ('pseudonymise', 'suppress', 'bucket')",
            name="ck_label_class_settings_mode",
        ),
        CheckConstraint("bucket_size > 0", name="ck_label_class_settings_bucket_size"),
    )

    label_class: str = Field(primary_key=True, max_length=32)
    mode: str = Field(max_length=16)
    bucket_size: int = Field(default=5, sa_column_kwargs={"server_default": "5"})
    updated_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )


class ScopeDimension(SQLModel, table=True):
    """Mirror of the scope dimensions plugins declare, synced at startup (D3.6)."""

    __tablename__ = "scope_dimensions"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    source: str = Field(primary_key=True, max_length=64)
    entity: str = Field(primary_key=True, max_length=64)
    dimension: str = Field(primary_key=True, max_length=64)
    self_attribute: str | None = Field(default=None, max_length=64)
    description: str = Field(default="", max_length=200)
    synced_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
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


REQUEST_KINDS: Final = ("group", "role", "resource")
REQUEST_STATUSES: Final = ("pending", "approved", "declined", "cancelled")
_PENDING = "status = 'pending'"


class AccessRequest(SQLModel, table=True):
    """A user's ask for a group, a role or an exact resource (spec §3.2 step 4).

    At most one pending request per (user_id, kind, target): a partial unique index.
    """

    __tablename__ = "access_requests"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr
    __table_args__ = (
        CheckConstraint(
            "kind IN ('group', 'role', 'resource')", name="ck_access_requests_kind"
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'declined', 'cancelled')",
            name="ck_access_requests_status",
        ),
        Index(
            "uq_access_requests_one_pending",
            "user_id",
            "kind",
            "target",
            unique=True,
            sqlite_where=text(_PENDING),
            postgresql_where=text(_PENDING),
        ),
        Index(
            "ix_access_requests_tenant_status_created", "tenant", "status", "created_at"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant: str = Field(default=DEFAULT_TENANT, max_length=64)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    kind: str = Field(max_length=16)
    target: str = Field(max_length=200)
    note: str = Field(max_length=500)
    status: str = Field(default="pending", max_length=16)
    decided_by: UUID | None = Field(default=None, foreign_key="users.id")
    decided_at: datetime | None = Field(default=None, sa_type=TIMESTAMP(timezone=True))
    decision_note: str = Field(default="", max_length=500)
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )


# Keyset paging and the summary window of the admin decision log (phase 5) read
# atlas_audit_log by (created_at, id). The index is declared here, not in
# app/models/audit.py, because that table's module is shared with phases 3 and 4
# (contracts.md); access owns the only reader that needs it. Migration 0006
# creates it.
Index(
    "ix_atlas_audit_log_created_at_id",
    col(AtlasAuditLog.created_at),
    col(AtlasAuditLog.id),
)

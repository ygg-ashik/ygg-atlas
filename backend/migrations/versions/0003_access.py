"""Access control (spec §7, §11.2) and the phase-2 ownership cleanup.

- New tables: capabilities, groups, group_members, grants, rbac_changes, policy_state.
- Seeds: policy_state (version 1) and the empty starter groups. Capabilities are
  synced from code at startup (app.access.startup), not here.
- atlas_audit_log gains user_id, auth_method, decision and deny_reason. user_id is
  backfilled from user_uid (an atlas id after 0002, a Firebase uid before it); the
  legacy column stays because the log is append-only.
- chat_sessions: user_id becomes required and the user_uid mirror is dropped.

Revision ID: 0003
Revises: 0002
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TS = sa.TIMESTAMP(timezone=True)
TENANT = "ygg"
STARTER_GROUPS = (
    ("atlas-admins", "People who administer atlas access"),
    ("leadership", "Company leadership"),
    ("marketing", "Marketing and growth"),
    ("csm", "Customer success managers"),
    ("risk-ops", "Risk and fraud operations"),
    ("engineering", "Engineering"),
)

_users = sa.table(
    "users", sa.column("id", sa.Uuid()), sa.column("firebase_uid", sa.String())
)
_audit = sa.table(
    "atlas_audit_log",
    sa.column("user_uid", sa.String()),
    sa.column("user_id", sa.Uuid()),
)
_sessions = sa.table(
    "chat_sessions", sa.column("user_uid", sa.String()), sa.column("user_id", sa.Uuid())
)
_groups = sa.table(
    "groups",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("description", sa.String()),
    sa.column("tenant", sa.String()),
    sa.column("created_at", TS),
)
_policy_state = sa.table(
    "policy_state",
    sa.column("id", sa.Integer()),
    sa.column("policy_version", sa.BigInteger()),
    sa.column("updated_at", TS),
)


def upgrade() -> None:
    _create_tables()
    _seed()
    _extend_audit()
    _require_session_owner()


def _create_tables() -> None:
    op.create_table(
        "capabilities",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("deprecated", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("groups.id"), nullable=True),
        sa.Column("tenant", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("tenant", "name", name="uq_groups_tenant_name"),
    )
    op.create_index("ix_groups_parent_id", "groups", ["parent_id"])
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("standing", sa.String(16), nullable=False),
        sa.Column("added_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("added_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
        sa.CheckConstraint(
            "standing IN ('member', 'manager')", name="ck_group_members_standing"
        ),
    )
    op.create_index("ix_group_members_user_id", "group_members", ["user_id"])
    op.create_table(
        "grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("subject_type", sa.String(16), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("effect", sa.String(16), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target", sa.String(200), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("expires_at", TS, nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint(
            "subject_type IN ('group', 'user')", name="ck_grants_subject_type"
        ),
        sa.CheckConstraint("effect IN ('allow', 'deny')", name="ck_grants_effect"),
        sa.CheckConstraint(
            "target_kind IN ('resource', 'capability', 'clearance')",
            name="ck_grants_target_kind",
        ),
    )
    op.create_index("ix_grants_subject_id", "grants", ["subject_id"])
    op.create_table(
        "rbac_changes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("via", sa.String(16), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", sa.String(100), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("at", TS, nullable=False),
    )
    op.create_index("ix_rbac_changes_actor_user_id", "rbac_changes", ["actor_user_id"])
    op.create_index("ix_rbac_changes_at", "rbac_changes", ["at"])
    op.create_table(
        "policy_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("policy_version", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )


def _seed() -> None:
    now = datetime.now(UTC)
    op.bulk_insert(_policy_state, [{"id": 1, "policy_version": 1, "updated_at": now}])
    op.bulk_insert(
        _groups,
        [
            {
                "id": uuid4(),
                "name": name,
                "description": description,
                "tenant": TENANT,
                "created_at": now,
            }
            for name, description in STARTER_GROUPS
        ],
    )


def _extend_audit() -> None:
    with op.batch_alter_table("atlas_audit_log") as batch:
        batch.add_column(sa.Column("user_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("auth_method", sa.String(16), nullable=True))
        batch.add_column(
            sa.Column("decision", sa.String(8), nullable=False, server_default="allow")
        )
        batch.add_column(sa.Column("deny_reason", sa.String(200), nullable=True))
        batch.create_index("ix_atlas_audit_log_user_id", ["user_id"])
        batch.create_foreign_key(
            "fk_atlas_audit_log_user_id_users", "users", ["user_id"], ["id"]
        )
    _backfill_audit_owners()


def _backfill_audit_owners() -> None:
    conn = op.get_bind()
    users = conn.execute(sa.select(_users.c.id, _users.c.firebase_uid)).all()
    by_id: dict[str, UUID] = {str(uid): uid for uid, _ in users}
    by_firebase: dict[str, UUID] = {fb: uid for uid, fb in users if fb}
    legacy = conn.execute(
        sa.select(_audit.c.user_uid).where(_audit.c.user_id.is_(None)).distinct()
    ).scalars()
    for user_uid in list(legacy):
        owner = by_id.get(user_uid) or by_firebase.get(user_uid)
        if owner is not None:
            conn.execute(
                _audit.update()
                .where(_audit.c.user_uid == user_uid)
                .where(_audit.c.user_id.is_(None))
                .values(user_id=owner)
            )


def _require_session_owner() -> None:
    orphans = (
        op.get_bind()
        .execute(
            sa.select(sa.func.count())
            .select_from(_sessions)
            .where(_sessions.c.user_id.is_(None))
        )
        .scalar_one()
    )
    if orphans:
        msg = (
            f"{orphans} chat sessions have no user_id; give each one an owner "
            "(see migration 0002's backfill) before upgrading"
        )
        raise RuntimeError(msg)
    with op.batch_alter_table("chat_sessions") as batch:
        batch.drop_index("ix_chat_sessions_user_uid")
        batch.drop_column("user_uid")
        batch.alter_column("user_id", existing_type=sa.Uuid(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch:
        batch.alter_column("user_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("user_uid", sa.String(), nullable=True))
    conn = op.get_bind()
    owners = conn.execute(sa.select(_sessions.c.user_id).distinct()).scalars()
    for owner in list(owners):
        conn.execute(
            _sessions.update()
            .where(_sessions.c.user_id == owner)
            .values(user_uid=str(owner))
        )
    with op.batch_alter_table("chat_sessions") as batch:
        batch.alter_column("user_uid", existing_type=sa.String(), nullable=False)
        batch.create_index("ix_chat_sessions_user_uid", ["user_uid"])
    with op.batch_alter_table("atlas_audit_log") as batch:
        batch.drop_constraint("fk_atlas_audit_log_user_id_users", type_="foreignkey")
        batch.drop_index("ix_atlas_audit_log_user_id")
        for column in ("deny_reason", "decision", "auth_method", "user_id"):
            batch.drop_column(column)
    for table in (
        "policy_state",
        "rbac_changes",
        "grants",
        "group_members",
        "groups",
        "capabilities",
    ):
        op.drop_table(table)

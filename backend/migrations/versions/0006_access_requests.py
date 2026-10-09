"""Access requests (spec §7 `access_requests`, §3.2 step 4).

- New table: access_requests. A user asks for a group, a role or an exact resource;
  a group manager or admin approves or declines it.
- A partial unique index allows at most one *pending* request per
  (user_id, kind, target): the database, not a race-prone pre-check, holds that rule.
  Decided and cancelled rows never block a new request.
- New index on atlas_audit_log (created_at, id): keyset paging and the summary
  window of the admin decision log.

Revision ID: 0006
Revises: 0003 (set to the chain predecessor at integration)
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0003"  # chain: set to predecessor at integration
branch_labels = None
depends_on = None

TS = sa.TIMESTAMP(timezone=True)
PENDING = sa.text("status = 'pending'")


def upgrade() -> None:
    op.create_table(
        "access_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("target", sa.String(200), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", TS, nullable=True),
        sa.Column("decision_note", sa.String(500), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint(
            "kind IN ('group', 'role', 'resource')", name="ck_access_requests_kind"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'declined', 'cancelled')",
            name="ck_access_requests_status",
        ),
    )
    op.create_index("ix_access_requests_user_id", "access_requests", ["user_id"])
    op.create_index(
        "uq_access_requests_one_pending",
        "access_requests",
        ["user_id", "kind", "target"],
        unique=True,
        sqlite_where=PENDING,
        postgresql_where=PENDING,
    )
    op.create_index(
        "ix_access_requests_tenant_status_created",
        "access_requests",
        ["tenant", "status", "created_at"],
    )
    op.create_index(
        "ix_atlas_audit_log_created_at_id", "atlas_audit_log", ["created_at", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_atlas_audit_log_created_at_id", "atlas_audit_log")
    op.drop_index("ix_access_requests_tenant_status_created", "access_requests")
    op.drop_index("uq_access_requests_one_pending", "access_requests")
    op.drop_index("ix_access_requests_user_id", "access_requests")
    op.drop_table("access_requests")

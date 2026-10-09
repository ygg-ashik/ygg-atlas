"""Row and field access (spec §5.5, §5.6, §7; auth phase 3).

- New tables: user_attributes (admin-set values `$self` resolves to),
  label_class_settings (how a breakdown label class is masked without its
  clearance) and scope_dimensions (the startup mirror of the dimensions plugins
  declare).
- Seeds: person_name=suppress and business_name=pseudonymise, bucket size 5.
  scope_dimensions is synced from code at startup (app.access.startup), not here.
- grants gains row_scope; atlas_audit_log gains scope, then masking. All three
  are appended at the end (cross-phase contract K2).

Deploy only together with the phase-3 code: an older backend ignores
grants.row_scope, so a scoped grant would read as an all-rows grant. The backend
runs this migration at container start. The downgrade refuses to run while any
scoped or clearance grant exists: revoke those first.

Revision ID: 0004
Revises: 0003
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"  # chain: set to predecessor at integration
branch_labels = None
depends_on = None

TS = sa.TIMESTAMP(timezone=True)
DEFAULT_BUCKET_SIZE = 5
LABEL_CLASS_SEEDS = (("person_name", "suppress"), ("business_name", "pseudonymise"))

_label_class_settings = sa.table(
    "label_class_settings",
    sa.column("label_class", sa.String()),
    sa.column("mode", sa.String()),
    sa.column("bucket_size", sa.Integer()),
    sa.column("updated_at", TS),
)


def upgrade() -> None:
    _create_tables()
    _seed()
    with op.batch_alter_table("grants") as batch:
        batch.add_column(sa.Column("row_scope", sa.JSON(), nullable=True))
    with op.batch_alter_table("atlas_audit_log") as batch:
        batch.add_column(sa.Column("scope", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("masking", sa.JSON(), nullable=True))


def _create_tables() -> None:
    op.create_table(
        "user_attributes",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.String(200), nullable=False),
        sa.Column("set_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("set_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("user_id", "key"),
    )
    op.create_table(
        "label_class_settings",
        sa.Column("label_class", sa.String(32), primary_key=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("bucket_size", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint(
            "mode IN ('pseudonymise', 'suppress', 'bucket')",
            name="ck_label_class_settings_mode",
        ),
        sa.CheckConstraint(
            "bucket_size > 0", name="ck_label_class_settings_bucket_size"
        ),
    )
    op.create_table(
        "scope_dimensions",
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("entity", sa.String(64), nullable=False),
        sa.Column("dimension", sa.String(64), nullable=False),
        sa.Column("self_attribute", sa.String(64), nullable=True),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("synced_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("source", "entity", "dimension"),
    )


def _seed() -> None:
    now = datetime.now(UTC)
    op.bulk_insert(
        _label_class_settings,
        [
            {
                "label_class": label_class,
                "mode": mode,
                "bucket_size": DEFAULT_BUCKET_SIZE,
                "updated_at": now,
            }
            for label_class, mode in LABEL_CLASS_SEEDS
        ],
    )


_grants = sa.table(
    "grants",
    sa.column("target_kind", sa.String()),
    sa.column("row_scope", sa.JSON()),
)


def _refuse_while_phase_3_grants_exist() -> None:
    """Older code ignores row_scope and clearance grants: dropping row_scope
    would turn a scoped allow into an all-rows allow (fail open)."""
    rows = op.get_bind().execute(
        sa.select(_grants.c.target_kind, _grants.c.row_scope).where(
            sa.or_(
                _grants.c.row_scope.is_not(None),
                _grants.c.target_kind == "clearance",
            )
        )
    )
    # A JSON null (what the ORM writes for None) is an all-rows grant.
    blocking = [
        r for r in rows if r.target_kind == "clearance" or r.row_scope is not None
    ]
    if blocking:
        raise RuntimeError(
            f"0004 downgrade refused: {len(blocking)} grant(s) have a row_scope or "
            "target_kind='clearance'; revoke them first (README, deploy notes)"
        )


def downgrade() -> None:
    _refuse_while_phase_3_grants_exist()
    with op.batch_alter_table("atlas_audit_log") as batch:
        batch.drop_column("masking")
        batch.drop_column("scope")
    with op.batch_alter_table("grants") as batch:
        batch.drop_column("row_scope")
    for table in ("scope_dimensions", "label_class_settings", "user_attributes"):
        op.drop_table(table)

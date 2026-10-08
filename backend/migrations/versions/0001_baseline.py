"""Baseline: the schema create_all produced before Alembic (chat + audit + blocks).

Idempotent: deployments that already have these tables (from create_all) upgrade
without error, so no manual `alembic stamp` is needed.

Revision ID: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.TIMESTAMP(timezone=True)


def _existing() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    existing = _existing()
    if "chat_sessions" not in existing:
        op.create_table(
            "chat_sessions",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("user_uid", sa.String(), nullable=False),
            sa.Column("user_email", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("created_at", TS, nullable=False),
            sa.Column("updated_at", TS, nullable=False),
        )
        op.create_index("ix_chat_sessions_user_uid", "chat_sessions", ["user_uid"])
    if "chat_messages" not in existing:
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "session_id",
                sa.Uuid(),
                sa.ForeignKey("chat_sessions.id"),
                nullable=False,
            ),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("content", sa.String(), nullable=False),
            sa.Column("provenance", sa.JSON(), nullable=True),
            sa.Column("blocks", sa.JSON(), nullable=True),
            sa.Column("model", sa.String(), nullable=True),
            sa.Column("token_usage", sa.JSON(), nullable=True),
            sa.Column("feedback_rating", sa.String(), nullable=True),
            sa.Column("feedback_category", sa.String(), nullable=True),
            sa.Column("created_at", TS, nullable=False),
        )
        op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    elif "blocks" not in _columns("chat_messages"):
        # Databases built by create_all before Track C's answer blocks (spec §11.1).
        with op.batch_alter_table("chat_messages") as batch:
            batch.add_column(sa.Column("blocks", sa.JSON(), nullable=True))
    if "atlas_audit_log" not in existing:
        op.create_table(
            "atlas_audit_log",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("user_uid", sa.String(), nullable=False),
            sa.Column("session_id", sa.Uuid(), nullable=True),
            sa.Column("surface", sa.String(), nullable=False),
            sa.Column("tool", sa.String(), nullable=False),
            sa.Column("arguments", sa.JSON(), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False),
            sa.Column("error", sa.String(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", TS, nullable=False),
        )
        op.create_index("ix_atlas_audit_log_user_uid", "atlas_audit_log", ["user_uid"])
        op.create_index(
            "ix_atlas_audit_log_session_id", "atlas_audit_log", ["session_id"]
        )


def downgrade() -> None:
    # Irreversible on purpose: these tables usually pre-date Alembic (adopted, not
    # created, by this baseline), and dropping them destroys chat history and the
    # audit log.
    msg = "0001 baseline is irreversible; restore from a backup instead"
    raise RuntimeError(msg)

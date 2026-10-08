"""Users table; chat sessions owned by atlas user ids (spec §7, §11.3).

Backfill: one user per legacy owner uid (one email each; owners sharing an email share
a user). Sessions get user_id, and user_uid is rewritten to the atlas user id so the
guardrails' daily limit stays consistent. atlas_audit_log is append-only and is NOT
rewritten: pre-0002 audit rows keep the Firebase uid (or "dev-user") and join to users
via users.firebase_uid (ARCHITECTURE.md §6).

Revision ID: 0002
Revises: 0001
"""

from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TS = sa.TIMESTAMP(timezone=True)
LEGACY_DEV_UID = "dev-user"

_users = sa.table(
    "users",
    sa.column("id", sa.Uuid()),
    sa.column("email", sa.String()),
    sa.column("firebase_uid", sa.String()),
    sa.column("display_name", sa.String()),
    sa.column("status", sa.String()),
    sa.column("kind", sa.String()),
    sa.column("role", sa.String()),
    sa.column("tenant", sa.String()),
    sa.column("created_at", TS),
)
_sessions = sa.table(
    "chat_sessions",
    sa.column("user_uid", sa.String()),
    sa.column("user_email", sa.String()),
    sa.column("user_id", sa.Uuid()),
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("firebase_uid", sa.String(length=128), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("tenant", sa.String(length=64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_firebase_uid", "users", ["firebase_uid"], unique=True)
    with op.batch_alter_table("chat_sessions") as batch:
        batch.add_column(sa.Column("user_id", sa.Uuid(), nullable=True))
        batch.create_index("ix_chat_sessions_user_id", ["user_id"])
        batch.create_foreign_key(
            "fk_chat_sessions_user_id_users", "users", ["user_id"], ["id"]
        )
    _backfill()


def _owner_emails(conn: sa.Connection) -> dict[str, str]:
    """One email per legacy owner uid (the uid is what must stay unique).

    Prefers a non-empty email; rows saved without one fall back to a placeholder.
    """
    rows = conn.execute(
        sa.select(_sessions.c.user_uid, _sessions.c.user_email)
        .where(_sessions.c.user_id.is_(None))
        .distinct()
    ).all()
    emails: dict[str, str] = {}
    for legacy_uid, raw_email in sorted(rows, key=lambda r: (r[0], r[1] or "")):
        email = (raw_email or "").strip().lower()
        if email or legacy_uid not in emails:
            emails[legacy_uid] = email
    return {
        uid: email or f"{uid}@unknown.invalid" for uid, email in sorted(emails.items())
    }


def _backfill() -> None:
    conn = op.get_bind()
    by_email: dict[str, UUID] = {}
    for legacy_uid, email in _owner_emails(conn).items():
        user_id = by_email.get(email)
        if user_id is None:
            # Two legacy uids sharing an email join one user; the second uid is
            # linked by email at its next sign-in.
            user_id = uuid4()
            by_email[email] = user_id
            conn.execute(
                _users.insert().values(
                    id=user_id,
                    email=email,
                    firebase_uid=None if legacy_uid == LEGACY_DEV_UID else legacy_uid,
                    display_name="",
                    status="active",
                    kind="human",
                    role="viewer",
                    tenant="ygg",
                    created_at=sa.func.current_timestamp(),
                )
            )
        conn.execute(
            _sessions.update()
            .where(_sessions.c.user_uid == legacy_uid)
            .where(_sessions.c.user_id.is_(None))
            .values(user_id=user_id, user_uid=str(user_id))
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch:
        batch.drop_constraint("fk_chat_sessions_user_id_users", type_="foreignkey")
        batch.drop_index("ix_chat_sessions_user_id")
        batch.drop_column("user_id")
    op.drop_index("ix_users_firebase_uid", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

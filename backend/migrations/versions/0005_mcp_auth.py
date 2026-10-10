"""MCP authentication (auth phase 4, spec §7, §11.5).

- New tables: oauth_clients, api_tokens, oauth_authorization_requests, oauth_codes,
  credential_events. Every secret is stored as a SHA-256 hash only.
- atlas_audit_log gains token_id and client_id, APPENDED after the existing columns
  (no foreign keys: the log outlives garbage-collected credential rows).
- The shared MCP identity (mcp-shared@atlas.internal) is disabled, with an
  rbac_changes row and a policy_version bump like any status change (D17, C13).

Revision ID: 0005
Revises: 0004
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TS = sa.TIMESTAMP(timezone=True)
TENANT = "ygg"
SHARED_MCP_EMAIL = "mcp-shared@atlas.internal"
_VIA = "migration"
_ACTION = "user.status"

_users = sa.table(
    "users",
    sa.column("id", sa.Uuid()),
    sa.column("email", sa.String()),
    sa.column("status", sa.String()),
)
_rbac_changes = sa.table(
    "rbac_changes",
    sa.column("id", sa.Uuid()),
    sa.column("actor_user_id", sa.Uuid()),
    sa.column("via", sa.String()),
    sa.column("tenant", sa.String()),
    sa.column("action", sa.String()),
    sa.column("object_type", sa.String()),
    sa.column("object_id", sa.String()),
    sa.column("before", sa.JSON()),
    sa.column("after", sa.JSON()),
    sa.column("at", TS),
)
_policy_state = sa.table(
    "policy_state",
    sa.column("id", sa.Integer()),
    sa.column("policy_version", sa.BigInteger()),
    sa.column("updated_at", TS),
)


def upgrade() -> None:
    _create_clients()
    _create_tokens()
    _create_requests_and_codes()
    _create_events()
    with op.batch_alter_table("atlas_audit_log") as batch:  # APPENDED (D25)
        batch.add_column(sa.Column("token_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("client_id", sa.String(255), nullable=True))
    _retire_shared_mcp_user()


def _create_clients() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(255), primary_key=True),
        sa.Column("client_name", sa.String(100), nullable=True),
        sa.Column("redirect_uris", sa.JSON(), nullable=False),
        sa.Column("token_endpoint_auth_method", sa.String(32), nullable=False),
        sa.Column("client_secret_hash", sa.String(64), nullable=True),
        sa.Column("grant_types", sa.JSON(), nullable=False),
        sa.Column("response_types", sa.JSON(), nullable=False),
        sa.Column("software_id", sa.String(200), nullable=True),
        sa.Column("registered_at", TS, nullable=False),
        sa.Column("last_used_at", TS, nullable=True),
        sa.Column("revoked_at", TS, nullable=True),
    )


def _create_tokens() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "client_id",
            sa.String(255),
            sa.ForeignKey("oauth_clients.client_id"),
            nullable=True,
        ),
        sa.Column("family_id", sa.Uuid(), nullable=True),
        sa.Column("audience", sa.String(500), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("last_used_at", TS, nullable=True),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("revoked_reason", sa.String(32), nullable=True),
        sa.CheckConstraint(
            "kind IN ('pat', 'service', 'oauth_access', 'oauth_refresh')",
            name="ck_api_tokens_kind",
        ),
    )
    op.create_index(
        "ix_api_tokens_token_hash", "api_tokens", ["token_hash"], unique=True
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])
    op.create_index("ix_api_tokens_client_id", "api_tokens", ["client_id"])
    op.create_index("ix_api_tokens_family_id", "api_tokens", ["family_id"])
    op.create_index("ix_api_tokens_user_id_kind", "api_tokens", ["user_id", "kind"])


def _create_requests_and_codes() -> None:
    op.create_table(
        "oauth_authorization_requests",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "client_id",
            sa.String(255),
            sa.ForeignKey("oauth_clients.client_id"),
            nullable=False,
        ),
        sa.Column("redirect_uri", sa.String(2000), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column("state", sa.String(500), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("resource", sa.String(500), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("consumed_at", TS, nullable=True),
    )
    op.create_index(
        "ix_oauth_authorization_requests_client_id",
        "oauth_authorization_requests",
        ["client_id"],
    )
    op.create_table(
        "oauth_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column(
            "client_id",
            sa.String(255),
            sa.ForeignKey("oauth_clients.client_id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column("redirect_uri", sa.String(2000), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("resource", sa.String(500), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("used_at", TS, nullable=True),
    )
    op.create_index(
        "ix_oauth_codes_code_hash", "oauth_codes", ["code_hash"], unique=True
    )
    op.create_index("ix_oauth_codes_client_id", "oauth_codes", ["client_id"])
    op.create_index("ix_oauth_codes_user_id", "oauth_codes", ["user_id"])


def _create_events() -> None:
    op.create_table(
        "credential_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("at", TS, nullable=False),
        sa.Column("event", sa.String(48), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("via", sa.String(16), nullable=False),
        sa.Column("token_id", sa.Uuid(), nullable=True),
        sa.Column("client_id", sa.String(255), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_credential_events_at", "credential_events", ["at"])
    op.create_index("ix_credential_events_user_id", "credential_events", ["user_id"])


def _set_shared_user_status(user_id: UUID, before: str, after: str) -> None:
    """A status change, audited and versioned like AccessAdmin.update_user's."""
    conn = op.get_bind()
    now = datetime.now(UTC)
    conn.execute(_users.update().where(_users.c.id == user_id).values(status=after))
    conn.execute(
        _rbac_changes.insert().values(
            id=uuid4(),
            actor_user_id=None,
            via=_VIA,
            tenant=TENANT,
            action=_ACTION,
            object_type="user",
            object_id=str(user_id),
            before={"status": before},
            after={"status": after},
            at=now,
        )
    )
    conn.execute(
        _policy_state.update()
        .where(_policy_state.c.id == 1)
        .values(policy_version=_policy_state.c.policy_version + 1, updated_at=now)
    )


def _retire_shared_mcp_user() -> None:
    """D17 + C13: the shared token is gone, so its identity is disabled."""
    row = (
        op.get_bind()
        .execute(
            sa.select(_users.c.id)
            .where(_users.c.email == SHARED_MCP_EMAIL)
            .where(_users.c.status == "active")
        )
        .first()
    )
    if row is not None:
        _set_shared_user_status(row.id, "active", "disabled")


def _restore_shared_mcp_user() -> None:
    """Re-enable the shared identity only if this migration was the last to change
    its status (an admin may have disabled it on purpose before 0005)."""
    conn = op.get_bind()
    row = conn.execute(
        sa.select(_users.c.id)
        .where(_users.c.email == SHARED_MCP_EMAIL)
        .where(_users.c.status == "disabled")
    ).first()
    if row is None:
        return
    last = conn.execute(
        sa.select(_rbac_changes.c.via, _rbac_changes.c.after)
        .where(_rbac_changes.c.object_type == "user")
        .where(_rbac_changes.c.object_id == str(row.id))
        .order_by(_rbac_changes.c.at.desc())
        .limit(1)
    ).first()
    if last is not None and last.via == _VIA and last.after == {"status": "disabled"}:
        _set_shared_user_status(row.id, "disabled", "active")


def downgrade() -> None:
    _restore_shared_mcp_user()
    with op.batch_alter_table("atlas_audit_log") as batch:
        batch.drop_column("client_id")
        batch.drop_column("token_id")
    for table in (
        "credential_events",
        "oauth_codes",
        "oauth_authorization_requests",
        "api_tokens",
        "oauth_clients",
    ):
        op.drop_table(table)

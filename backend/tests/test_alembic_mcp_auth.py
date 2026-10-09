"""Migration 0005: credential tables, audit credential columns, the shared MCP user."""

from pathlib import Path
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlmodel import SQLModel

import app.access.models  # registers access tables
import app.identity.models  # registers users and credential tables
import app.models  # noqa: F401  # registers chat and audit tables

BACKEND = Path(__file__).parents[1]
MIGRATION = BACKEND / "migrations" / "versions" / "0005_mcp_auth.py"
CREDENTIAL_TABLES = (
    "oauth_clients",
    "api_tokens",
    "oauth_authorization_requests",
    "oauth_codes",
    "credential_events",
)
SHARED_MCP_EMAIL = "mcp-shared@atlas.internal"


def _config(url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _tables(sync_url: str) -> set[str]:
    engine = sa.create_engine(sync_url)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _seed_user(sync_url: str, email: str, status: str = "active") -> UUID:
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid()),
        sa.column("email", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("status", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("role", sa.String()),
        sa.column("tenant", sa.String()),
        sa.column("created_at", sa.TIMESTAMP(timezone=True)),
    )
    user_id = uuid4()
    engine = sa.create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(
            users.insert().values(
                id=user_id,
                email=email,
                display_name="MCP (shared token)",
                status=status,
                kind="service",
                role="viewer",
                tenant="ygg",
                created_at=sa.func.current_timestamp(),
            )
        )
    engine.dispose()
    return user_id


def _state(sync_url: str) -> tuple[str | None, list[sa.Row[tuple[str, str]]], int]:
    """(shared user's status, rbac_changes (via, action) rows, policy_version)."""
    engine = sa.create_engine(sync_url)
    with engine.connect() as conn:
        status = conn.execute(
            sa.text("SELECT status FROM users WHERE email = :e"),
            {"e": SHARED_MCP_EMAIL},
        ).scalar_one_or_none()
        changes = list(
            conn.execute(sa.text("SELECT via, action FROM rbac_changes")).all()
        )
        version = conn.execute(
            sa.text("SELECT policy_version FROM policy_state WHERE id = 1")
        ).scalar_one()
    engine.dispose()
    return status, changes, version


def test_0005_creates_credential_tables(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db}"), "head")
    assert set(CREDENTIAL_TABLES) <= _tables(f"sqlite:///{db}")


def test_0005_credential_tables_match_the_models(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db}"), "head")
    engine = sa.create_engine(f"sqlite:///{db}")
    inspector = sa.inspect(engine)
    try:
        for table in CREDENTIAL_TABLES:
            declared = SQLModel.metadata.tables[table]
            migrated = {c["name"] for c in inspector.get_columns(table)}
            assert migrated == set(declared.columns.keys()), table
            indexes = {
                (i["name"], tuple(i["column_names"]), bool(i["unique"]))
                for i in inspector.get_indexes(table)
            }
            assert indexes == {
                (i.name, tuple(c.name for c in i.columns), bool(i.unique))
                for i in declared.indexes
            }, table
    finally:
        engine.dispose()


def test_0005_appends_audit_credential_columns(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db}"), "head")
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        columns = [c["name"] for c in sa.inspect(engine).get_columns("atlas_audit_log")]
    finally:
        engine.dispose()
    assert columns[-2:] == ["token_id", "client_id"]
    declared = list(SQLModel.metadata.tables["atlas_audit_log"].columns.keys())
    assert declared[-2:] == ["token_id", "client_id"]


def test_0005_disables_the_shared_mcp_user_and_bumps_the_version(
    tmp_path: Path,
) -> None:
    db = tmp_path / "m.db"
    config = _config(f"sqlite+aiosqlite:///{db}")
    command.upgrade(config, "0003")
    user_id = _seed_user(f"sqlite:///{db}", SHARED_MCP_EMAIL)
    _, _, version_before = _state(f"sqlite:///{db}")

    command.upgrade(config, "0005")

    status, changes, version = _state(f"sqlite:///{db}")
    assert status == "disabled"
    assert [tuple(c) for c in changes] == [("migration", "user.status")]
    assert version == version_before + 1
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        object_id = conn.execute(sa.text("SELECT object_id FROM rbac_changes")).scalar()
    engine.dispose()
    assert object_id == str(user_id)


def test_0005_without_the_shared_user_is_a_no_op(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    config = _config(f"sqlite+aiosqlite:///{db}")
    command.upgrade(config, "0003")
    _, _, version_before = _state(f"sqlite:///{db}")

    command.upgrade(config, "0005")

    status, changes, version = _state(f"sqlite:///{db}")
    assert status is None
    assert changes == []
    assert version == version_before


def test_0005_leaves_an_already_disabled_shared_user_alone(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    config = _config(f"sqlite+aiosqlite:///{db}")
    command.upgrade(config, "0003")
    _seed_user(f"sqlite:///{db}", SHARED_MCP_EMAIL, status="disabled")
    _, _, version_before = _state(f"sqlite:///{db}")

    command.upgrade(config, "0005")

    status, changes, version = _state(f"sqlite:///{db}")
    assert (status, changes, version) == ("disabled", [], version_before)


def test_0005_round_trips(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    config = _config(f"sqlite+aiosqlite:///{db}")
    command.upgrade(config, "0003")
    _seed_user(f"sqlite:///{db}", SHARED_MCP_EMAIL)

    command.upgrade(config, "head")
    command.downgrade(config, "0003")

    assert not set(CREDENTIAL_TABLES) & _tables(f"sqlite:///{db}")
    status, changes, _ = _state(f"sqlite:///{db}")
    assert status == "active"  # the downgrade re-enables it, audited
    assert [tuple(c) for c in changes] == [("migration", "user.status")] * 2
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        audit = {c["name"] for c in sa.inspect(engine).get_columns("atlas_audit_log")}
    finally:
        engine.dispose()
    assert not {"token_id", "client_id"} & audit

    command.upgrade(config, "head")
    assert set(CREDENTIAL_TABLES) <= _tables(f"sqlite:///{db}")


def test_0005_down_revision_is_marked_for_the_chain() -> None:
    source = MIGRATION.read_text()
    assert 'revision = "0005"' in source
    assert (
        'down_revision = "0003"  # chain: set to predecessor at integration' in source
    )

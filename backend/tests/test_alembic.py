"""Alembic owns the schema: it must build exactly what the models declare."""

from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlmodel import SQLModel

import app.identity.models  # registers users on the metadata
import app.models  # noqa: F401  # registers chat and audit tables

BACKEND = Path(__file__).parents[1]


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


def test_upgrade_from_empty_creates_baseline_tables(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db}"), "0001")
    assert {"chat_sessions", "chat_messages", "atlas_audit_log"} <= _tables(
        f"sqlite:///{db}"
    )


def test_baseline_is_idempotent_over_existing_tables(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE chat_sessions (id CHAR(32) PRIMARY KEY)"))
        conn.execute(
            sa.text(
                "CREATE TABLE chat_messages (id CHAR(32) PRIMARY KEY, content TEXT)"
            )
        )
    engine.dispose()

    command.upgrade(_config(f"sqlite+aiosqlite:///{db}"), "0001")

    assert {"chat_sessions", "chat_messages", "atlas_audit_log"} <= _tables(
        f"sqlite:///{db}"
    )
    engine = sa.create_engine(f"sqlite:///{db}")
    columns = {c["name"] for c in sa.inspect(engine).get_columns("chat_messages")}
    engine.dispose()
    assert "blocks" in columns  # pre-Track-C databases gain the answer blocks column


def _seed_legacy_sessions(sync_url: str) -> None:
    sessions = sa.table(
        "chat_sessions",
        sa.column("id", sa.Uuid()),
        sa.column("user_uid", sa.String()),
        sa.column("user_email", sa.String()),
        sa.column("title", sa.String()),
        sa.column("created_at", sa.TIMESTAMP(timezone=True)),
        sa.column("updated_at", sa.TIMESTAMP(timezone=True)),
    )
    now = sa.func.current_timestamp()
    engine = sa.create_engine(sync_url)
    with engine.begin() as conn:
        for uid, email in [
            ("fb-sara", "Sara@yougotagift.com"),
            ("fb-sara", "Sara@yougotagift.com"),
            ("fb-sara", ""),  # same Firebase uid, a row with no email recorded
            ("dev-user", "dev@yougotagift.com"),
            ("fb-ghost", ""),
        ]:
            conn.execute(
                sessions.insert().values(
                    id=uuid4(),
                    user_uid=uid,
                    user_email=email,
                    title="t",
                    created_at=now,
                    updated_at=now,
                )
            )
    engine.dispose()


def test_backfill_links_legacy_sessions_to_users(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    config = _config(f"sqlite+aiosqlite:///{db}")
    command.upgrade(config, "0001")
    _seed_legacy_sessions(f"sqlite:///{db}")

    command.upgrade(config, "0002")

    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        users = conn.execute(sa.text("SELECT email, firebase_uid FROM users")).all()
        unlinked = conn.execute(
            sa.text("SELECT COUNT(*) FROM chat_sessions WHERE user_id IS NULL")
        ).scalar_one()
        owners = set(
            conn.execute(sa.text("SELECT DISTINCT user_uid FROM chat_sessions"))
            .scalars()
            .all()
        )
    engine.dispose()

    assert sorted(users) == [
        ("dev@yougotagift.com", None),
        ("fb-ghost@unknown.invalid", "fb-ghost"),
        ("sara@yougotagift.com", "fb-sara"),
    ]
    assert unlinked == 0
    assert not owners & {"fb-sara", "dev-user", "fb-ghost"}  # now atlas user ids


def test_downgrade_to_baseline_then_upgrade_round_trips(tmp_path: Path) -> None:
    config = _config(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
    command.upgrade(config, "head")
    command.downgrade(config, "0001")
    command.upgrade(config, "head")


def test_baseline_refuses_to_downgrade(tmp_path: Path) -> None:
    # The baseline adopts pre-Alembic tables; dropping them would destroy chat
    # history and the audit log.
    config = _config(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
    command.upgrade(config, "0001")
    with pytest.raises(RuntimeError, match="irreversible"):
        command.downgrade(config, "base")


def test_head_matches_model_columns(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db}"), "head")
    engine = sa.create_engine(f"sqlite:///{db}")
    inspector = sa.inspect(engine)
    try:
        for table in ("users", "chat_sessions", "chat_messages", "atlas_audit_log"):
            migrated = {c["name"] for c in inspector.get_columns(table)}
            declared = set(SQLModel.metadata.tables[table].columns.keys())
            assert migrated == declared, table
    finally:
        engine.dispose()

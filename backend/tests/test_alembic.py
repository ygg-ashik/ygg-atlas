"""Alembic owns the schema: it must build exactly what the models declare."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel

import app.access.models  # registers access tables
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
        for table in (
            "users",
            "chat_sessions",
            "chat_messages",
            "atlas_audit_log",
            "capabilities",
            "groups",
            "group_members",
            "grants",
            "rbac_changes",
            "policy_state",
            "user_attributes",
            "label_class_settings",
            "scope_dimensions",
        ):
            migrated = {c["name"] for c in inspector.get_columns(table)}
            declared = set(SQLModel.metadata.tables[table].columns.keys())
            assert migrated == declared, table
    finally:
        engine.dispose()


STARTER_GROUPS = {
    "atlas-admins",
    "leadership",
    "marketing",
    "csm",
    "risk-ops",
    "engineering",
}


def test_access_tables_and_seeds(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db}"), "head")
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        groups = set(conn.execute(sa.text("SELECT name FROM groups")).scalars())
        version = conn.execute(
            sa.text("SELECT policy_version FROM policy_state WHERE id = 1")
        ).scalar_one()
        session_columns = {
            c["name"] for c in sa.inspect(conn).get_columns("chat_sessions")
        }
    engine.dispose()
    assert groups == STARTER_GROUPS
    assert version == 1
    assert "user_uid" not in session_columns  # decision D6


def _seed_user_and_audit(sync_url: str, user_id: UUID, firebase_uid: str) -> None:
    engine = sa.create_engine(sync_url)
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid()),
        sa.column("email", sa.String()),
        sa.column("firebase_uid", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("status", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("role", sa.String()),
        sa.column("tenant", sa.String()),
        sa.column("created_at", sa.TIMESTAMP(timezone=True)),
    )
    audit = sa.table(
        "atlas_audit_log",
        sa.column("id", sa.Uuid()),
        sa.column("user_uid", sa.String()),
        sa.column("surface", sa.String()),
        sa.column("tool", sa.String()),
        sa.column("success", sa.Boolean()),
        sa.column("created_at", sa.TIMESTAMP(timezone=True)),
    )
    now = sa.func.current_timestamp()
    with engine.begin() as conn:
        conn.execute(
            users.insert().values(
                id=user_id,
                email="sara@yougotagift.com",
                firebase_uid=firebase_uid,
                display_name="",
                status="active",
                kind="human",
                role="viewer",
                tenant="ygg",
                created_at=now,
            )
        )
        for owner in (str(user_id), firebase_uid, "nobody"):
            conn.execute(
                audit.insert().values(
                    id=uuid4(),
                    user_uid=owner,
                    surface="chat",
                    tool="query_metric",
                    success=True,
                    created_at=now,
                )
            )
    engine.dispose()


def test_audit_rows_gain_user_id(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    config = _config(f"sqlite+aiosqlite:///{db}")
    command.upgrade(config, "0002")
    user_id = uuid4()
    _seed_user_and_audit(f"sqlite:///{db}", user_id, "fb-sara")

    command.upgrade(config, "0003")

    engine = sa.create_engine(f"sqlite:///{db}")
    audit = sa.table(
        "atlas_audit_log",
        sa.column("user_uid", sa.String()),
        sa.column("user_id", sa.Uuid()),
    )
    with engine.connect() as conn:
        rows = conn.execute(sa.select(audit.c.user_uid, audit.c.user_id)).all()
    owners: dict[str, UUID | None] = {r.user_uid: r.user_id for r in rows}
    engine.dispose()
    assert owners[str(user_id)] == user_id
    assert owners["fb-sara"] == user_id  # pre-0002 rows join through firebase_uid
    assert owners["nobody"] is None


def test_sessions_without_an_owner_stop_the_migration(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    config = _config(f"sqlite+aiosqlite:///{db}")
    command.upgrade(config, "0002")
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO chat_sessions (id, user_uid, user_email, title, "
                "created_at, updated_at) VALUES (:id, 'orphan', '', 't', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": uuid4().hex},
        )
    engine.dispose()
    with pytest.raises(RuntimeError, match="no user_id"):
        command.upgrade(config, "0003")

    # The check runs before any DDL, so a failed run leaves the database at 0002
    # (SQLite does not roll back DDL).
    assert "groups" not in _tables(f"sqlite:///{db}")
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        version = conn.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    engine.dispose()
    assert version == "0002"


def test_malformed_grant_rows_are_rejected(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db}"), "head")
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO grants (id, subject_type, subject_id, effect, "
                    "target_kind, target, reason, created_at) VALUES (:id, 'user', "
                    ":subject, 'DENY', 'resource', '*', '', CURRENT_TIMESTAMP)"
                ),
                {"id": uuid4().hex, "subject": uuid4().hex},
            )
    finally:
        engine.dispose()


ROW_FIELD_TABLES = {"user_attributes", "label_class_settings", "scope_dimensions"}


def _column_order(sync_url: str, table: str) -> list[str]:
    engine = sa.create_engine(sync_url)
    try:
        return [c["name"] for c in sa.inspect(engine).get_columns(table)]
    finally:
        engine.dispose()


def test_row_field_tables_and_seeds(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db}"), "head")
    sync_url = f"sqlite:///{db}"
    engine = sa.create_engine(sync_url)
    with engine.connect() as conn:
        modes = set(
            conn.execute(
                sa.text(
                    "SELECT label_class, mode, bucket_size FROM label_class_settings"
                )
            ).tuples()
        )
    engine.dispose()

    assert _tables(sync_url) >= ROW_FIELD_TABLES
    assert modes == {
        ("person_name", "suppress", 5),
        ("business_name", "pseudonymise", 5),
    }
    # Appended (contract K2): phase 3's columns, then phase 4's credential ones.
    assert _column_order(sync_url, "grants")[-1] == "row_scope"
    assert _column_order(sync_url, "atlas_audit_log")[-4:] == [
        "scope",
        "masking",
        "token_id",
        "client_id",
    ]


def test_row_field_model_columns_are_appended() -> None:
    def last(table: str, n: int) -> list[str]:
        return list(SQLModel.metadata.tables[table].columns.keys())[-n:]

    assert last("grants", 1) == ["row_scope"]
    assert last("atlas_audit_log", 4) == ["scope", "masking", "token_id", "client_id"]


def test_row_field_downgrade_round_trips(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    sync_url = f"sqlite:///{db}"
    config = _config(f"sqlite+aiosqlite:///{db}")
    command.upgrade(config, "0004")

    command.downgrade(config, "0003")

    assert not ROW_FIELD_TABLES & _tables(sync_url)
    assert "row_scope" not in _column_order(sync_url, "grants")
    assert not {"scope", "masking"} & set(_column_order(sync_url, "atlas_audit_log"))

    command.upgrade(config, "0004")

    assert _tables(sync_url) >= ROW_FIELD_TABLES
    assert _column_order(sync_url, "atlas_audit_log")[-2:] == ["scope", "masking"]


@pytest.mark.parametrize(
    ("mode", "bucket_size"), [("hide", 5), ("bucket", 0)], ids=["mode", "bucket_size"]
)
def test_bad_label_mode_is_rejected(
    tmp_path: Path, mode: str, bucket_size: int
) -> None:
    db = tmp_path / "m.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db}"), "head")
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE label_class_settings SET mode = :mode, "
                    "bucket_size = :size WHERE label_class = 'person_name'"
                ),
                {"mode": mode, "size": bucket_size},
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("target_kind", "target", "row_scope"),
    [
        ("resource", "deepsales/*", '{"csm": ["Sara"]}'),
        ("resource", "deepsales/*", "{}"),
        ("clearance", "fields:people_names", None),
    ],
    ids=["scoped", "empty_scope", "clearance"],
)
def test_row_field_downgrade_refuses_while_phase_3_grants_exist(
    tmp_path: Path, target_kind: str, target: str, row_scope: str | None
) -> None:
    # Older code ignores row_scope and clearance grants, so dropping them would
    # turn a scoped allow into an all-rows allow (fail open).
    db = tmp_path / "m.db"
    config = _config(f"sqlite+aiosqlite:///{db}")
    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO grants (id, subject_type, subject_id, effect, "
                "target_kind, target, reason, created_at, row_scope) VALUES (:id, "
                "'user', :subject, 'allow', :kind, :target, '', CURRENT_TIMESTAMP, "
                ":scope)"
            ),
            {
                "id": uuid4().hex,
                "subject": uuid4().hex,
                "kind": target_kind,
                "target": target,
                "scope": row_scope,
            },
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="revoke"):
        command.downgrade(config, "0003")

    assert "row_scope" in _column_order(f"sqlite:///{db}", "grants")


def test_row_field_downgrade_allows_unscoped_grants(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    config = _config(f"sqlite+aiosqlite:///{db}")
    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        # A JSON null (what the ORM writes for None) is an all-rows grant.
        for scope in (None, "null"):
            conn.execute(
                sa.text(
                    "INSERT INTO grants (id, subject_type, subject_id, effect, "
                    "target_kind, target, reason, created_at, row_scope) VALUES "
                    "(:id, 'user', :subject, 'allow', 'resource', '*', '', "
                    "CURRENT_TIMESTAMP, :scope)"
                ),
                {"id": uuid4().hex, "subject": uuid4().hex, "scope": scope},
            )
    engine.dispose()

    command.downgrade(config, "0003")

    assert "row_scope" not in _column_order(f"sqlite:///{db}", "grants")

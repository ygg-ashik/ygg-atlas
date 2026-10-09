"""BOOTSTRAP_ADMINS at startup (spec §3.3): create missing admins through the
audited path, never re-elevate an existing user."""

from sqlalchemy import func
from sqlmodel import col, select
from structlog.testing import capture_logs

from app.access.models import RbacChange
from app.access.startup import prepare_access
from app.identity.models import User, UserKind
from tests.access_helpers import make_user, policy_version


async def _user(db, email: str) -> User | None:
    stmt = (
        select(User)
        .where(col(User.email) == email)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _bootstrap_changes(db) -> list[RbacChange]:
    stmt = select(RbacChange).where(col(RbacChange.via) == "bootstrap")
    return list((await db.execute(stmt)).scalars().all())


async def test_a_new_bootstrap_admin_is_created_audited_and_bumped(db) -> None:
    before = await policy_version(db)

    await prepare_access(db, ["boss@yougotagift.com"])

    boss = await _user(db, "boss@yougotagift.com")
    assert boss is not None
    assert boss.role == "admin"
    changes = await _bootstrap_changes(db)
    assert len(changes) == 1
    change = changes[0]
    assert (change.actor_user_id, change.object_type) == (None, "user")
    assert change.object_id == str(boss.id)
    assert change.before is None
    assert change.after is not None
    assert change.after["role"] == "admin"
    assert await policy_version(db) == before + 1


async def test_a_demoted_existing_user_stays_demoted_and_is_logged(db) -> None:
    demoted = await make_user(db, "boss@yougotagift.com", role="viewer")
    demoted_id = demoted.id

    with capture_logs() as logs:
        await prepare_access(db, ["boss@yougotagift.com"])

    stored = await _user(db, "boss@yougotagift.com")
    assert stored is not None
    assert stored.role == "viewer"
    assert await _bootstrap_changes(db) == []
    skipped = [e for e in logs if e["event"] == "identity.bootstrap_admin_skipped"]
    assert len(skipped) == 1
    assert skipped[0]["user_id"] == str(demoted_id)
    assert skipped[0]["log_level"] == "warning"


async def test_an_existing_admin_is_left_alone_silently(db) -> None:
    await make_user(db, "boss@yougotagift.com", role="admin")

    with capture_logs() as logs:
        await prepare_access(db, ["boss@yougotagift.com"])

    assert await _bootstrap_changes(db) == []
    assert not [e for e in logs if e["event"] == "identity.bootstrap_admin_skipped"]


async def test_a_service_user_is_never_made_admin(db) -> None:
    await make_user(db, "svc@yougotagift.com", role="analyst", kind="service")

    with capture_logs() as logs:
        await prepare_access(db, ["svc@yougotagift.com"])

    stored = await _user(db, "svc@yougotagift.com")
    assert stored is not None
    assert (stored.role, stored.kind) == ("analyst", UserKind.SERVICE)
    assert [e for e in logs if e["event"] == "identity.bootstrap_admin_skipped"]


async def test_bootstrap_is_idempotent(db) -> None:
    await prepare_access(db, ["boss@yougotagift.com", "ops@yougotagift.com"])
    await prepare_access(db, ["boss@yougotagift.com", "ops@yougotagift.com"])

    users = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(col(User.email).in_(["boss@yougotagift.com", "ops@yougotagift.com"]))
        )
    ).scalar_one()
    assert users == 2
    assert len(await _bootstrap_changes(db)) == 2


async def test_no_bootstrap_admins_writes_no_users(db) -> None:
    await prepare_access(db)

    assert await _bootstrap_changes(db) == []

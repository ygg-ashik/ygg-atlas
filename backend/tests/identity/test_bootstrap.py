from structlog.testing import capture_logs

from app.identity import bootstrap_admins
from app.identity.models import User, UserKind
from app.identity.repository import UserRepository


async def test_creates_missing_admins_and_upgrades_existing(db) -> None:
    users = UserRepository(db)
    await users.save(User(email="ops@yougotagift.com", role="viewer"))

    changed = await bootstrap_admins(
        db, ["ashik@yougotagift.com", "ops@yougotagift.com"]
    )

    assert changed == 2
    for email in ("ashik@yougotagift.com", "ops@yougotagift.com"):
        user = await users.get_by_email(email)
        assert user is not None
        assert user.role == "admin"


async def test_is_idempotent(db) -> None:
    await bootstrap_admins(db, ["ashik@yougotagift.com"])
    assert await bootstrap_admins(db, ["ashik@yougotagift.com"]) == 0


async def test_skips_an_email_that_belongs_to_a_service_user(db) -> None:
    users = UserRepository(db)
    service = await users.save(
        User(email="svc@yougotagift.com", kind=UserKind.SERVICE, role="analyst")
    )

    with capture_logs() as logs:
        changed = await bootstrap_admins(db, ["svc@yougotagift.com"])

    assert changed == 0
    stored = await users.get(service.id)
    assert stored is not None
    assert stored.role == "analyst"
    events = [
        log for log in logs if log["event"] == "identity.bootstrap_skips_service_user"
    ]
    assert len(events) == 1
    assert events[0]["user_id"] == str(service.id)

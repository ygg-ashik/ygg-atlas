from app.identity import bootstrap_admins
from app.identity.models import User
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

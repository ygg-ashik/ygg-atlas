from app.identity.models import User, UserStatus
from app.identity.repository import UserRepository


async def test_save_and_lookup_by_email_and_firebase_uid(db) -> None:
    users = UserRepository(db)
    saved = await users.save(User(email="sara@yougotagift.com", firebase_uid="fb-sara"))

    assert await users.get(saved.id) is not None
    by_email = await users.get_by_email("SARA@yougotagift.com")
    by_uid = await users.get_by_firebase_uid("fb-sara")
    assert by_email is not None
    assert by_email.id == saved.id
    assert by_uid is not None
    assert by_uid.id == saved.id
    assert saved.status == UserStatus.ACTIVE
    assert saved.role == "viewer"
    assert saved.tenant == "ygg"


async def test_lookups_return_none_when_missing(db) -> None:
    users = UserRepository(db)
    assert await users.get_by_email("nobody@yougotagift.com") is None
    assert await users.get_by_firebase_uid("fb-none") is None

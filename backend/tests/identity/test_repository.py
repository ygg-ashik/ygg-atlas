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


async def test_create_or_get_returns_the_winner_on_conflict(db) -> None:
    users = UserRepository(db)
    winner = await users.save(User(email="sara@yougotagift.com", firebase_uid="fb-1"))

    # A concurrent first sign-in lost the race: same identity, inserted second.
    loser = await users.create_or_get(
        User(email="sara@yougotagift.com", firebase_uid="fb-1")
    )

    assert loser.id == winner.id


async def test_create_or_get_inserts_when_free(db) -> None:
    users = UserRepository(db)
    created = await users.create_or_get(User(email="new@yougotagift.com"))
    assert await users.get(created.id) is not None


async def test_conflict_keeps_other_pending_work_in_the_session(db) -> None:
    users = UserRepository(db)
    await users.save(User(email="sara@yougotagift.com", firebase_uid="fb-1"))
    db.add(User(email="pending@yougotagift.com"))  # caller's uncommitted work

    await users.create_or_get(User(email="sara@yougotagift.com", firebase_uid="fb-1"))
    await db.commit()

    assert await users.get_by_email("pending@yougotagift.com") is not None

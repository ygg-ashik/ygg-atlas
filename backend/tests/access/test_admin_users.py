import pytest

from app.access.admin import Actor
from app.access.cache import PolicyCache
from app.access.errors import AccessDeniedError, ConflictError, InvalidChangeError
from app.access.repository import AccessRepository
from app.access.schemas import GroupCreate, UserUpdate
from app.access.service import AccessService
from app.identity.tokens import VerifiedToken
from tests.access_helpers import actor_with, add_grant, admin_for, make_user

REVENUE = "demo/order/revenue"


class RecordingVerifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.revoked: list[str] = []
        self.fail = fail

    async def verify(self, token: str) -> VerifiedToken:
        raise AssertionError("not used")

    async def revoke(self, firebase_uid: str) -> None:
        if self.fail:
            raise RuntimeError("no service-account credentials")
        self.revoked.append(firebase_uid)


async def test_a_role_change_is_audited_and_takes_effect(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    admin = admin_for(db)

    await admin.update_user(actor, sara.id, UserUpdate(role="analyst"))

    policy = await AccessService(AccessRepository(db), PolicyCache()).policy_for_user(
        sara.id
    )
    assert policy.has("mcp:use")
    change = (await admin.list_changes(actor))[0]
    assert (change.action, change.before, change.after) == (
        "user.role",
        {"role": "viewer"},
        {"role": "analyst"},
    )


async def test_unknown_roles_and_empty_updates_are_rejected(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    sara_id = sara.id  # captured before a raising call expires the row
    with pytest.raises(InvalidChangeError, match="Unknown role"):
        await admin_for(db).update_user(actor, sara_id, UserUpdate(role="owner"))
    with pytest.raises(InvalidChangeError, match="Nothing to change"):
        await admin_for(db).update_user(actor, sara_id, UserUpdate())


async def test_nobody_changes_their_own_role_or_status(db) -> None:
    actor = await actor_with(db)
    assert actor.user_id is not None
    for update in (UserUpdate(role="viewer"), UserUpdate(status="disabled")):
        with pytest.raises(ConflictError):
            await admin_for(db).update_user(actor, actor.user_id, update)


async def test_disabling_ends_firebase_sessions(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com", firebase_uid="fb-sara")
    verifier = RecordingVerifier()

    user = await admin_for(db, verifier).update_user(
        actor, sara.id, UserUpdate(status="disabled")
    )

    assert user.status == "disabled"
    assert verifier.revoked == ["fb-sara"]
    policy = await AccessService(AccessRepository(db), PolicyCache()).policy_for_user(
        sara.id
    )
    assert not policy.active


async def test_a_failed_revocation_still_disables(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com", firebase_uid="fb-sara")
    user = await admin_for(db, RecordingVerifier(fail=True)).update_user(
        actor, sara.id, UserUpdate(status="disabled")
    )
    assert user.status == "disabled"


async def test_user_search_is_case_insensitive(db) -> None:
    actor = await actor_with(db)
    await make_user(db, "sara.ali@yougotagift.com")
    users = await admin_for(db).list_users(actor, "SARA")
    assert [u.email for u in users] == ["sara.ali@yougotagift.com"]


async def test_effective_access_names_the_deciding_grant(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    grant = await add_grant(db, sara, "demo/*")

    policy = await admin_for(db).effective_access(actor, sara.id)

    rule = policy.decide(REVENUE).rule
    assert rule is not None
    assert rule.grant_id == grant.id


async def test_the_change_log_needs_admin_audit_and_is_newest_first(db) -> None:
    with pytest.raises(AccessDeniedError):
        await admin_for(db).list_changes(await actor_with(db, "builder"))
    actor = await actor_with(db)
    admin = admin_for(db)
    await admin.create_group(actor, GroupCreate(name="first"))
    await admin.create_group(actor, GroupCreate(name="second"))

    changes = await admin.list_changes(actor)

    assert len(changes) == 2
    assert changes[0].at >= changes[1].at


# ---- D10: no escalation through roles ---------------------------------------


async def test_an_actor_cannot_assign_a_role_with_more_access_than_their_own(
    db,
) -> None:
    builder = await actor_with(db, "builder")
    assert builder.user_id is not None
    user = await AccessRepository(db).user(builder.user_id)
    assert user is not None
    await add_grant(db, user, "admin:users", kind="capability")
    policy = await AccessService(AccessRepository(db), PolicyCache()).policy_for_user(
        user.id
    )
    actor = Actor.from_policy(policy)
    sara = await make_user(db, "sara@yougotagift.com")

    with pytest.raises(AccessDeniedError):
        await admin_for(db).update_user(actor, sara.id, UserUpdate(role="admin"))


async def test_an_admin_can_assign_any_role(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")

    user = await admin_for(db).update_user(actor, sara.id, UserUpdate(role="admin"))

    assert user.role == "admin"

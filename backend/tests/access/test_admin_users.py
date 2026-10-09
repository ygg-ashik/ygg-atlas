from uuid import uuid4

import pytest

from app.access.admin import Actor
from app.access.cache import PolicyCache
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.repository import AccessRepository
from app.access.schemas import GroupCreate, UserUpdate
from app.access.service import AccessService
from app.identity.models import User
from app.identity.tokens import VerifiedToken
from tests.access_helpers import (
    actor_with,
    add_grant,
    admin_for,
    fresh,
    make_user,
    policy_version,
)

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


async def _actor_with_capabilities(db, *capabilities: str) -> Actor:
    """A builder actor with exactly these extra capabilities, nothing assumed."""
    base = await actor_with(db, "builder")
    assert base.user_id is not None
    user = await AccessRepository(db).user(base.user_id)
    assert user is not None
    for capability in capabilities:
        await add_grant(db, user, capability, kind="capability")
    policy = await AccessService(AccessRepository(db), PolicyCache()).policy_for_user(
        user.id
    )
    return Actor.from_policy(policy)


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
        with pytest.raises(ConflictError, match="your own"):
            await admin_for(db).update_user(actor, actor.user_id, update)


async def test_disabling_ends_firebase_sessions(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com", firebase_uid="fb-sara")
    verifier = RecordingVerifier()
    cache = PolicyCache()
    service = AccessService(AccessRepository(db), cache)
    before = await service.policy_for_user(sara.id)
    assert before.active

    user = await admin_for(db, verifier).update_user(
        actor, sara.id, UserUpdate(status="disabled")
    )

    assert user.status == "disabled"
    assert verifier.revoked == ["fb-sara"]
    # Same cache, same service: only the version bump can make it see the change.
    after = await service.policy_for_user(sara.id)
    assert not after.active


async def test_a_failed_revocation_still_disables(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com", firebase_uid="fb-sara")
    user = await admin_for(db, RecordingVerifier(fail=True)).update_user(
        actor, sara.id, UserUpdate(status="disabled")
    )
    assert user.status == "disabled"


async def test_re_enabling_does_not_call_revoke(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(
        db, "sara@yougotagift.com", status="disabled", firebase_uid="fb-sara"
    )
    verifier = RecordingVerifier()

    user = await admin_for(db, verifier).update_user(
        actor, sara.id, UserUpdate(status="active")
    )

    assert user.status == "active"
    assert verifier.revoked == []


async def test_disabling_an_already_disabled_user_does_not_call_revoke(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(
        db, "sara@yougotagift.com", status="disabled", firebase_uid="fb-sara"
    )
    verifier = RecordingVerifier()

    user = await admin_for(db, verifier).update_user(
        actor, sara.id, UserUpdate(status="disabled")
    )

    assert user.status == "disabled"
    assert verifier.revoked == []


async def test_a_no_op_update_writes_no_change_and_leaves_the_version_unchanged(
    db,
) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    before_version = await policy_version(db)

    user = await admin_for(db).update_user(
        actor, sara.id, UserUpdate(role="viewer", status="active")
    )

    assert user.role == "viewer"
    assert await policy_version(db) == before_version
    assert await admin_for(db).list_changes(actor) == []


async def test_changing_both_fields_writes_one_change(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")

    await admin_for(db).update_user(
        actor, sara.id, UserUpdate(role="analyst", status="disabled")
    )

    changes = await admin_for(db).list_changes(actor)
    assert len(changes) == 1
    assert changes[0].action == "user.update"
    assert changes[0].before == {"role": "viewer", "status": "active"}
    assert changes[0].after == {"role": "analyst", "status": "disabled"}


async def test_user_search_is_case_insensitive(db) -> None:
    actor = await actor_with(db)
    await make_user(db, "sara.ali@yougotagift.com")
    users = await admin_for(db).list_users(actor, "SARA")
    assert [u.email for u in users] == ["sara.ali@yougotagift.com"]


async def test_list_users_excludes_other_tenants_and_matches_display_name(db) -> None:
    actor = await actor_with(db)
    nina = User(email="nina@yougotagift.com", display_name="Nina Diaz")
    db.add(nina)
    other_tenant = User(email="nina@acme.example", tenant="acme")
    db.add(other_tenant)
    await db.commit()

    by_name = await admin_for(db).list_users(actor, "Diaz")
    assert [u.email for u in by_name] == ["nina@yougotagift.com"]

    wildcard = await admin_for(db).list_users(actor, "%")
    assert wildcard == []

    all_users = await admin_for(db).list_users(actor)
    assert "nina@acme.example" not in [u.email for u in all_users]


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
    await admin.create_group(await fresh(db, actor), GroupCreate(name="second"))

    changes = await admin.list_changes(actor)

    assert len(changes) == 2
    assert changes[0].at >= changes[1].at


async def test_changes_in_another_tenant_are_not_listed(db) -> None:
    other = User(email="admin@acme.example", role="admin", tenant="acme")
    db.add(other)
    await db.commit()
    other_policy = await AccessService(
        AccessRepository(db), PolicyCache()
    ).policy_for_user(other.id)
    other_actor = Actor.from_policy(other_policy)
    await admin_for(db).create_group(other_actor, GroupCreate(name="acme-group"))

    actor = await actor_with(db)
    changes = await admin_for(db).list_changes(actor)

    assert changes == []


async def test_unknown_or_cross_tenant_user_id_is_not_found(db) -> None:
    actor = await actor_with(db)
    other = User(email="someone@acme.example", tenant="acme")
    db.add(other)
    await db.commit()
    other_id = other.id

    for target in (uuid4(), other_id):
        with pytest.raises(NotFoundError):
            await admin_for(db).update_user(actor, target, UserUpdate(role="analyst"))
        with pytest.raises(NotFoundError):
            await admin_for(db).effective_access(actor, target)


async def test_denied_before_lookup_for_an_unknown_id(db) -> None:
    actor = await actor_with(db, "builder")
    with pytest.raises(AccessDeniedError):
        await admin_for(db).update_user(actor, uuid4(), UserUpdate(role="analyst"))


# ---- D10: no escalation through roles, or onto users above you --------------


async def test_an_actor_cannot_assign_a_role_with_more_access_than_their_own(
    db,
) -> None:
    actor = await _actor_with_capabilities(db, "admin:users")
    sara = await make_user(db, "sara@yougotagift.com")

    with pytest.raises(AccessDeniedError, match="more access than your own"):
        await admin_for(db).update_user(actor, sara.id, UserUpdate(role="admin"))


async def test_an_admin_can_assign_any_role(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")

    user = await admin_for(db).update_user(actor, sara.id, UserUpdate(role="admin"))

    assert user.role == "admin"


async def test_a_builder_with_admin_users_can_promote_a_viewer(db) -> None:
    actor = await _actor_with_capabilities(db, "admin:users")
    for role in ("analyst", "builder"):
        sara = await make_user(db, "sara@yougotagift.com")
        actor = await fresh(db, actor)
        user = await admin_for(db).update_user(actor, sara.id, UserUpdate(role=role))
        assert user.role == role


async def test_a_builder_with_admin_users_cannot_demote_an_admin(db) -> None:
    actor = await _actor_with_capabilities(db, "admin:users")
    victim = await make_user(db, "victim@yougotagift.com", role="admin")

    with pytest.raises(AccessDeniedError, match="more access than your own"):
        await admin_for(db).update_user(actor, victim.id, UserUpdate(role="viewer"))


async def test_a_builder_with_admin_users_cannot_disable_an_admin(db) -> None:
    actor = await _actor_with_capabilities(db, "admin:users")
    victim = await make_user(db, "victim@yougotagift.com", role="admin")

    with pytest.raises(AccessDeniedError, match="more access than your own"):
        await admin_for(db).update_user(actor, victim.id, UserUpdate(status="disabled"))


# ---- D10 also judges a disabled target by the access they'd regain ----------


async def test_a_builder_cannot_re_enable_a_disabled_admin(db) -> None:
    admin_actor = await actor_with(db)
    victim = await make_user(db, "victim@yougotagift.com", role="admin")
    victim_id = victim.id  # captured before any call that may expire the row
    await admin_for(db).update_user(
        admin_actor, victim_id, UserUpdate(status="disabled")
    )
    builder = await _actor_with_capabilities(db, "admin:users")

    with pytest.raises(AccessDeniedError, match="more access than your own"):
        await admin_for(db).update_user(builder, victim_id, UserUpdate(status="active"))


async def test_a_builder_cannot_change_a_disabled_admins_role(db) -> None:
    admin_actor = await actor_with(db)
    victim = await make_user(db, "victim@yougotagift.com", role="admin")
    victim_id = victim.id
    await admin_for(db).update_user(
        admin_actor, victim_id, UserUpdate(status="disabled")
    )
    builder = await _actor_with_capabilities(db, "admin:users")

    with pytest.raises(AccessDeniedError, match="more access than your own"):
        await admin_for(db).update_user(builder, victim_id, UserUpdate(role="viewer"))


async def test_a_builder_can_re_enable_a_disabled_viewer(db) -> None:
    admin_actor = await actor_with(db)
    victim = await make_user(db, "victim@yougotagift.com", role="viewer")
    victim_id = victim.id
    await admin_for(db).update_user(
        admin_actor, victim_id, UserUpdate(status="disabled")
    )
    builder = await _actor_with_capabilities(db, "admin:users")

    user = await admin_for(db).update_user(
        builder, victim_id, UserUpdate(status="active")
    )

    assert user.status == "active"

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.access.admin import AccessAdmin, Actor
from app.access.cache import PolicyCache
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.models import Group, RbacChange
from app.access.repository import AccessRepository
from app.access.schemas import GroupCreate, GroupUpdate
from app.access.service import AccessService
from tests.access_helpers import (
    actor_with,
    add_grant,
    admin_for,
    make_group,
    make_user,
    policy_version,
)


async def _changes(db) -> list[RbacChange]:
    stmt = select(RbacChange).order_by(col(RbacChange.at))
    return list((await db.execute(stmt)).scalars().all())


async def test_create_group_is_audited_and_bumps_the_version(db) -> None:
    actor = await actor_with(db)
    before = await policy_version(db)

    group = await admin_for(db).create_group(
        actor, GroupCreate(name="growth", description="Growth team")
    )

    assert group.tenant == "ygg"
    assert await policy_version(db) == before + 1
    change = (await _changes(db))[-1]
    assert (change.action, change.object_id, change.via) == (
        "group.create",
        str(group.id),
        "api",
    )
    assert change.actor_user_id == actor.user_id
    assert change.before is None
    assert change.after is not None
    assert change.after["name"] == "growth"


async def test_group_names_are_unique(db) -> None:
    actor = await actor_with(db)
    admin = admin_for(db)
    await admin.create_group(actor, GroupCreate(name="growth"))
    with pytest.raises(ConflictError):
        await admin.create_group(actor, GroupCreate(name="growth"))


async def test_only_admin_groups_creates_groups(db) -> None:
    builder = await actor_with(db, "builder")
    with pytest.raises(AccessDeniedError, match="admin:groups"):
        await admin_for(db).create_group(builder, GroupCreate(name="x"))


async def test_an_unknown_parent_is_not_found(db) -> None:
    with pytest.raises(NotFoundError):
        await admin_for(db).create_group(
            await actor_with(db), GroupCreate(name="x", parent_id=uuid4())
        )


async def test_a_group_cannot_move_under_itself_or_a_subgroup(db) -> None:
    actor = await actor_with(db)
    admin = admin_for(db)
    parent = await admin.create_group(actor, GroupCreate(name="marketing"))
    child = await admin.create_group(
        actor, GroupCreate(name="growth", parent_id=parent.id)
    )
    # Captured as plain UUIDs: a failed write below rolls back and (correctly,
    # per the new lock_for_write/_write robustness) expires every ORM object
    # in the session, so `parent`/`child` themselves are no longer safe to
    # read attributes from afterward.
    parent_id, child_id = parent.id, child.id

    with pytest.raises(InvalidChangeError):
        await admin.update_group(actor, parent_id, GroupUpdate(parent_id=child_id))
    with pytest.raises(InvalidChangeError):
        await admin.update_group(actor, parent_id, GroupUpdate(parent_id=parent_id))

    moved = await admin.update_group(actor, child_id, GroupUpdate(parent_id=None))
    assert moved.parent_id is None
    renamed = await admin.update_group(actor, child_id, GroupUpdate(name="growth-mena"))
    assert renamed.name == "growth-mena"


async def test_only_empty_groups_can_be_deleted(db) -> None:
    actor = await actor_with(db)
    admin = admin_for(db)
    used = await admin.create_group(actor, GroupCreate(name="used"))
    await add_grant(db, used, "demo/*")
    with pytest.raises(ConflictError):
        await admin.delete_group(actor, used.id)

    empty = await admin.create_group(actor, GroupCreate(name="empty"))
    await admin.delete_group(actor, empty.id)
    assert "empty" not in {g.name for g in await admin.list_groups(actor)}
    assert (await _changes(db))[-1].action == "group.delete"


async def test_admins_add_members_and_managers(db) -> None:
    actor = await actor_with(db)
    admin = admin_for(db)
    group = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")

    added = await admin.put_member(actor, group.id, sara.id, "manager")

    assert (added.email, added.standing) == ("sara@yougotagift.com", "manager")
    listed = await admin.list_members(actor, group.id)
    assert [(m.email, m.standing) for m in listed] == [
        ("sara@yougotagift.com", "manager")
    ]


async def test_managers_manage_members_of_their_subtree(db) -> None:
    parent = await make_group(db, "marketing")
    child = await make_group(db, "growth", parent=parent)
    manager = await actor_with(db, "viewer", member_of=parent, standing="manager")
    sara = await make_user(db, "sara@yougotagift.com")
    admin = admin_for(db)
    # Plain UUIDs: the denied promotion below rolls back and expires every
    # ORM object in the session (decision: _write rolls back on any error
    # so the session stays usable for the next write).
    child_id, sara_id = child.id, sara.id

    await admin.put_member(manager, child_id, sara_id, "member")
    with pytest.raises(AccessDeniedError):  # decision D8: only admins appoint managers
        await admin.put_member(manager, child_id, sara_id, "manager")
    await admin.remove_member(manager, child_id, sara_id)


async def test_plain_members_cannot_change_membership(db) -> None:
    group = await make_group(db, "growth")
    member = await actor_with(db, "viewer", member_of=group)
    sara = await make_user(db, "sara@yougotagift.com")
    with pytest.raises(AccessDeniedError):
        await admin_for(db).put_member(member, group.id, sara.id, "member")


async def test_removing_a_non_member_is_not_found(db) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "growth")
    with pytest.raises(NotFoundError):
        await admin_for(db).remove_member(actor, group.id, uuid4())


async def test_the_cli_actor_is_trusted_and_recorded(db) -> None:
    await admin_for(db).create_group(Actor.cli(), GroupCreate(name="from-cli"))
    change = (await _changes(db))[-1]
    assert (change.via, change.actor_user_id) == ("cli", None)


# ---- code-review follow-ups -------------------------------------------------


async def test_a_manager_cannot_demote_a_co_manager(db) -> None:
    """Closes the D8 hole: put_member(..., "member") must not be a back door
    around removing a manager without admin:groups."""
    admin_actor = await actor_with(db)
    admin = admin_for(db)
    parent = await admin.create_group(admin_actor, GroupCreate(name="marketing"))
    child = await admin.create_group(
        admin_actor, GroupCreate(name="growth", parent_id=parent.id)
    )
    bob = await make_user(db, "bob@yougotagift.com")
    await admin.put_member(admin_actor, child.id, bob.id, "manager")
    parent_manager = await actor_with(
        db, "viewer", member_of=parent, standing="manager"
    )

    with pytest.raises(AccessDeniedError):
        await admin.put_member(parent_manager, child.id, bob.id, "member")


async def test_a_manager_cannot_remove_a_co_manager(db) -> None:
    admin_actor = await actor_with(db)
    admin = admin_for(db)
    group = await admin.create_group(admin_actor, GroupCreate(name="growth"))
    bob = await make_user(db, "bob@yougotagift.com")
    await admin.put_member(admin_actor, group.id, bob.id, "manager")
    manager = await actor_with(db, "viewer", member_of=group, standing="manager")

    with pytest.raises(AccessDeniedError):
        await admin.remove_member(manager, group.id, bob.id)


async def test_a_commit_conflict_maps_to_conflict_and_the_session_stays_usable(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = await actor_with(db)
    repo = AccessRepository(db)
    admin = AccessAdmin(repo, AccessService(repo, PolicyCache()))
    real_commit = repo.commit
    calls = {"n": 0}

    async def flaky_commit() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("insert", {}, Exception("dup"))
        await real_commit()

    monkeypatch.setattr(repo, "commit", flaky_commit)

    with pytest.raises(ConflictError):
        await admin.create_group(actor, GroupCreate(name="first"))

    group = await admin.create_group(actor, GroupCreate(name="second"))
    assert group.name == "second"


async def test_an_unchanged_update_does_not_bump_the_version(db) -> None:
    actor = await actor_with(db)
    admin = admin_for(db)
    group = await admin.create_group(actor, GroupCreate(name="growth"))
    before = await policy_version(db)

    unchanged = await admin.update_group(actor, group.id, GroupUpdate(name="growth"))

    assert unchanged.name == "growth"
    assert await policy_version(db) == before
    assert (await _changes(db))[-1].action == "group.create"  # no update row added


async def test_putting_a_member_at_their_current_standing_does_not_bump_the_version(
    db,
) -> None:
    actor = await actor_with(db)
    admin = admin_for(db)
    group = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    await admin.put_member(actor, group.id, sara.id, "member")
    before = await policy_version(db)

    unchanged = await admin.put_member(actor, group.id, sara.id, "member")

    assert unchanged.standing == "member"
    assert await policy_version(db) == before


async def test_an_invalid_standing_is_rejected(db) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    with pytest.raises(InvalidChangeError):
        await admin_for(db).put_member(actor, group.id, sara.id, "owner")


async def test_a_manager_without_admin_role_cannot_manage_groups(db) -> None:
    group = await make_group(db, "growth")
    manager = await actor_with(db, "viewer", member_of=group, standing="manager")
    admin = admin_for(db)

    with pytest.raises(AccessDeniedError):
        await admin.create_group(manager, GroupCreate(name="x"))
    with pytest.raises(AccessDeniedError):
        await admin.update_group(manager, group.id, GroupUpdate(name="y"))
    with pytest.raises(AccessDeniedError):
        await admin.delete_group(manager, group.id)


async def test_a_manager_cannot_touch_a_sibling_groups_members(db) -> None:
    admin_actor = await actor_with(db)
    admin = admin_for(db)
    sales = await admin.create_group(admin_actor, GroupCreate(name="sales"))
    growth = await admin.create_group(admin_actor, GroupCreate(name="growth"))
    manager = await actor_with(db, "viewer", member_of=sales, standing="manager")
    sara = await make_user(db, "sara@yougotagift.com")

    with pytest.raises(AccessDeniedError):
        await admin.put_member(manager, growth.id, sara.id, "member")


async def test_a_group_in_another_tenant_is_not_found(db) -> None:
    actor = await actor_with(db)
    other = Group(name="eu-team", tenant="acme")
    db.add(other)
    await db.commit()

    with pytest.raises(NotFoundError):
        await admin_for(db).update_group(actor, other.id, GroupUpdate(name="x"))


async def test_put_member_on_an_unknown_user_is_not_found(db) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "growth")
    with pytest.raises(NotFoundError):
        await admin_for(db).put_member(actor, group.id, uuid4(), "member")


async def test_put_member_is_audited_and_bumps_the_version(db) -> None:
    actor = await actor_with(db)
    admin = admin_for(db)
    group = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    before = await policy_version(db)

    await admin.put_member(actor, group.id, sara.id, "member")

    assert await policy_version(db) == before + 1
    assert (await _changes(db))[-1].action == "member.put"

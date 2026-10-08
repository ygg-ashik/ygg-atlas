from uuid import uuid4

import pytest
from sqlmodel import col, select

from app.access.admin import Actor
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.models import RbacChange
from app.access.schemas import GroupCreate, GroupUpdate
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

    with pytest.raises(InvalidChangeError):
        await admin.update_group(actor, parent.id, GroupUpdate(parent_id=child.id))
    with pytest.raises(InvalidChangeError):
        await admin.update_group(actor, parent.id, GroupUpdate(parent_id=parent.id))

    moved = await admin.update_group(actor, child.id, GroupUpdate(parent_id=None))
    assert moved.parent_id is None
    renamed = await admin.update_group(actor, child.id, GroupUpdate(name="growth-mena"))
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

    await admin.put_member(manager, child.id, sara.id, "member")
    with pytest.raises(AccessDeniedError):  # decision D8: only admins appoint managers
        await admin.put_member(manager, child.id, sara.id, "manager")
    await admin.remove_member(manager, child.id, sara.id)


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

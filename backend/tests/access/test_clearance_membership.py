"""Membership can't smuggle a clearance past C10.

Joining a group (or moving one under a parent) inherits its live clearance
allows; leaving one (or moving away) lifts its clearance denies. Either widens
what names a member sees, so an API actor needs that clearance themself; the
trusted CLI is exempt.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.access.admin import Actor
from app.access.catalog import CLEARANCE_PEOPLE_NAMES
from app.access.errors import AccessDeniedError
from app.access.models import Group
from app.access.repository import AccessRepository
from app.access.schemas import GroupUpdate
from tests.access_helpers import (
    actor_with,
    add_grant,
    add_member,
    admin_for,
    fresh,
    make_group,
    make_user,
)


async def _cleared_admin(db) -> Actor:
    base = await actor_with(db)
    assert base.user_id is not None
    user = await AccessRepository(db).user(base.user_id)
    assert user is not None
    await add_grant(db, user, CLEARANCE_PEOPLE_NAMES, kind="clearance")
    return await fresh(db, base)


async def _cleared_tree(db) -> tuple[Group, Group]:
    """A parent holding the clearance allow, and a child under it."""
    parent = await make_group(db, "csm")
    child = await make_group(db, "csm-uae", parent=parent)
    await add_grant(db, parent, CLEARANCE_PEOPLE_NAMES, kind="clearance")
    return parent, child


# ---- joining a cleared group ---------------------------------------------


async def test_an_uncleared_admin_cannot_add_a_member_under_a_clearance(db) -> None:
    _, child = await _cleared_tree(db)
    sara = await make_user(db, "sara@yougotagift.com")
    with pytest.raises(AccessDeniedError, match="clearance"):
        await admin_for(db).put_member(
            await actor_with(db), child.id, sara.id, "member"
        )


async def test_an_uncleared_manager_cannot_add_a_member_under_a_clearance(
    db,
) -> None:
    # The manager runs the parent; only the child carries the clearance, so
    # the manager doesn't hold it.
    parent = await make_group(db, "csm")
    child = await make_group(db, "csm-uae", parent=parent)
    await add_grant(db, child, CLEARANCE_PEOPLE_NAMES, kind="clearance")
    child_id = child.id  # commits below expire loaded rows
    manager = await actor_with(db, "viewer", member_of=parent, standing="manager")
    sara = await make_user(db, "sara@yougotagift.com")
    with pytest.raises(AccessDeniedError, match="clearance"):
        await admin_for(db).put_member(
            await fresh(db, manager), child_id, sara.id, "member"
        )


async def test_a_cleared_admin_and_the_cli_add_members_under_a_clearance(
    db,
) -> None:
    _, child = await _cleared_tree(db)
    sara = await make_user(db, "sara@yougotagift.com")
    omar = await make_user(db, "omar@yougotagift.com")
    admin = admin_for(db)

    added = await admin.put_member(
        await _cleared_admin(db), child.id, sara.id, "member"
    )
    assert added.user_id == sara.id
    added = await admin.put_member(Actor.cli(), child.id, omar.id, "member")
    assert added.user_id == omar.id


async def test_an_expired_clearance_allow_needs_no_clearance(db) -> None:
    group = await make_group(db, "csm")
    await add_grant(
        db,
        group,
        CLEARANCE_PEOPLE_NAMES,
        kind="clearance",
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    sara = await make_user(db, "sara@yougotagift.com")

    added = await admin_for(db).put_member(
        await actor_with(db), group.id, sara.id, "member"
    )
    assert added.user_id == sara.id


# ---- re-parenting ------------------------------------------------------------


async def test_moving_a_group_under_a_clearance_needs_it(db) -> None:
    parent, _ = await _cleared_tree(db)
    loose = await make_group(db, "ops")
    move = GroupUpdate.model_validate({"parent_id": parent.id})
    admin = admin_for(db)

    with pytest.raises(AccessDeniedError, match="clearance"):
        await admin.update_group(await actor_with(db), loose.id, move)

    moved = await admin.update_group(await _cleared_admin(db), loose.id, move)
    assert moved.parent_id == parent.id


async def test_the_cli_moves_a_group_under_a_clearance(db) -> None:
    parent, _ = await _cleared_tree(db)
    loose = await make_group(db, "ops")
    moved = await admin_for(db).update_group(
        Actor.cli(), loose.id, GroupUpdate.model_validate({"parent_id": parent.id})
    )
    assert moved.parent_id == parent.id


async def test_moving_a_group_out_from_under_a_clearance_deny_needs_it(db) -> None:
    parent = await make_group(db, "contractors")
    child = await make_group(db, "contractors-uae", parent=parent)
    await add_grant(db, parent, CLEARANCE_PEOPLE_NAMES, kind="clearance", effect="deny")
    detach = GroupUpdate.model_validate({"parent_id": None})

    with pytest.raises(AccessDeniedError, match="clearance"):
        await admin_for(db).update_group(await actor_with(db), child.id, detach)

    moved = await admin_for(db).update_group(await _cleared_admin(db), child.id, detach)
    assert moved.parent_id is None


async def test_a_rename_needs_no_clearance(db) -> None:
    _, child = await _cleared_tree(db)
    renamed = await admin_for(db).update_group(
        await actor_with(db), child.id, GroupUpdate.model_validate({"name": "uae"})
    )
    assert renamed.name == "uae"


# ---- leaving a clearance-deny group --------------------------------------


async def test_removing_a_member_under_a_clearance_deny_needs_it(db) -> None:
    parent = await make_group(db, "contractors")
    child = await make_group(db, "contractors-uae", parent=parent)
    await add_grant(db, parent, CLEARANCE_PEOPLE_NAMES, kind="clearance", effect="deny")
    sara = await make_user(db, "sara@yougotagift.com")
    omar = await make_user(db, "omar@yougotagift.com")
    child_id, sara_id, omar_id = child.id, sara.id, omar.id
    await add_member(db, child, sara)
    await add_member(db, child, omar)
    admin = admin_for(db)

    with pytest.raises(AccessDeniedError, match="clearance"):
        await admin.remove_member(await actor_with(db), child_id, sara_id)

    await admin.remove_member(await _cleared_admin(db), child_id, sara_id)
    await admin.remove_member(Actor.cli(), child_id, omar_id)
    assert await AccessRepository(db).member(child_id, sara_id) is None
    assert await AccessRepository(db).member(child_id, omar_id) is None

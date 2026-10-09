"""Managers can't widen access through membership (spec §5.3, D8/D10).

A manager may add and remove plain members of their subtree, but joining a
group yourself, lifting a deny by removing someone from a group under it, and
adding a service identity (the shared MCP user) all widen access through a
group, which is reserved for admin:groups holders.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.access.admin import Actor
from app.access.cache import PolicyCache
from app.access.errors import AccessDeniedError
from app.access.repository import AccessRepository
from app.access.service import AccessService
from tests.access_helpers import (
    actor_with,
    add_grant,
    add_member,
    admin_for,
    make_group,
    make_user,
)


async def _actor(db, user) -> Actor:
    policy = await AccessService(AccessRepository(db), PolicyCache()).policy_for_user(
        user.id
    )
    return Actor.from_policy(policy)


async def _manager_of(db, group, email: str = "mgr@yougotagift.com"):
    manager = await make_user(db, email, role="viewer")
    await add_member(db, group, manager, "manager")
    return manager


# ---- self-join, self-change, self-removal ------------------------------------


async def test_a_manager_cannot_add_themself_to_a_subgroup(db) -> None:
    parent = await make_group(db, "marketing")
    child = await make_group(db, "paid", parent=parent)
    await add_grant(db, child, "ads/*")
    manager = await _manager_of(db, parent)
    child_id, manager_id = child.id, manager.id

    with pytest.raises(AccessDeniedError):
        await admin_for(db).put_member(
            await _actor(db, manager), child_id, manager_id, "member"
        )

    policy = await AccessService(AccessRepository(db), PolicyCache()).policy_for_user(
        manager_id
    )
    assert not policy.allows("ads/campaign/spend")


async def test_an_admin_groups_holder_can_add_themself(db) -> None:
    group = await make_group(db, "marketing")
    admin_actor = await actor_with(db)
    assert admin_actor.user_id is not None

    added = await admin_for(db).put_member(
        admin_actor, group.id, admin_actor.user_id, "member"
    )

    assert added.user_id == admin_actor.user_id


async def test_a_manager_cannot_change_or_remove_their_own_membership(db) -> None:
    parent = await make_group(db, "marketing")
    child = await make_group(db, "paid", parent=parent)
    manager = await _manager_of(db, parent)
    await add_member(db, child, manager, "member")
    child_id, manager_id = child.id, manager.id
    admin = admin_for(db)

    with pytest.raises(AccessDeniedError):
        await admin.remove_member(await _actor(db, manager), child_id, manager_id)
    with pytest.raises(AccessDeniedError):
        await admin.put_member(
            await _actor(db, manager), child_id, manager_id, "member"
        )


# ---- removal that lifts a deny -------------------------------------------------


async def test_a_manager_cannot_remove_themself_from_a_deny_group(db) -> None:
    parent = await make_group(db, "sales")
    await add_grant(db, parent, "demo/*")
    child = await make_group(db, "interns", parent=parent)
    await add_grant(db, child, "demo/order/*", effect="deny")
    manager = await _manager_of(db, parent)
    await add_member(db, child, manager, "member")
    child_id, manager_id = child.id, manager.id

    with pytest.raises(AccessDeniedError):
        await admin_for(db).remove_member(
            await _actor(db, manager), child_id, manager_id
        )

    policy = await AccessService(AccessRepository(db), PolicyCache()).policy_for_user(
        manager_id
    )
    assert not policy.allows("demo/order/revenue")


async def test_a_manager_cannot_remove_a_member_from_a_deny_group(db) -> None:
    group = await make_group(db, "interns")
    await add_grant(db, group, "demo/order/*", effect="deny")
    manager = await _manager_of(db, group)
    sara = await make_user(db, "sara@yougotagift.com")
    await add_member(db, group, sara)

    with pytest.raises(AccessDeniedError):
        await admin_for(db).remove_member(await _actor(db, manager), group.id, sara.id)


async def test_a_deny_on_an_ancestor_also_blocks_removal(db) -> None:
    grand = await make_group(db, "company")
    await add_grant(db, grand, "finance/*", effect="deny")
    parent = await make_group(db, "sales", parent=grand)
    child = await make_group(db, "interns", parent=parent)
    manager = await _manager_of(db, parent)
    sara = await make_user(db, "sara@yougotagift.com")
    await add_member(db, child, sara)

    with pytest.raises(AccessDeniedError):
        await admin_for(db).remove_member(await _actor(db, manager), child.id, sara.id)


async def test_an_expired_deny_does_not_block_removal(db) -> None:
    group = await make_group(db, "interns")
    past = datetime.now(UTC) - timedelta(days=1)
    await add_grant(db, group, "demo/order/*", effect="deny", expires_at=past)
    manager = await _manager_of(db, group)
    sara = await make_user(db, "sara@yougotagift.com")
    await add_member(db, group, sara)

    await admin_for(db).remove_member(await _actor(db, manager), group.id, sara.id)


async def test_an_admin_groups_holder_can_remove_from_a_deny_group(db) -> None:
    group = await make_group(db, "interns")
    await add_grant(db, group, "demo/order/*", effect="deny")
    sara = await make_user(db, "sara@yougotagift.com")
    await add_member(db, group, sara)

    await admin_for(db).remove_member(await actor_with(db), group.id, sara.id)


async def test_the_cli_can_remove_from_a_deny_group(db) -> None:
    group = await make_group(db, "interns")
    await add_grant(db, group, "demo/order/*", effect="deny")
    sara = await make_user(db, "sara@yougotagift.com")
    await add_member(db, group, sara)

    await admin_for(db).remove_member(Actor.cli(), group.id, sara.id)


async def test_a_manager_still_manages_plain_members_without_denies(db) -> None:
    parent = await make_group(db, "marketing")
    await add_grant(db, parent, "ads/*")
    child = await make_group(db, "paid", parent=parent)
    manager = await _manager_of(db, parent)
    sara = await make_user(db, "sara@yougotagift.com")
    child_id, sara_id = child.id, sara.id
    admin = admin_for(db)

    await admin.put_member(await _actor(db, manager), child_id, sara_id, "member")
    await admin.remove_member(await _actor(db, manager), child_id, sara_id)


# ---- service identities ----------------------------------------------------------


async def test_a_manager_cannot_add_a_service_user(db) -> None:
    group = await make_group(db, "finance")
    await add_grant(db, group, "demo/*")
    service = await make_user(db, "mcp@atlas.internal", role="analyst", kind="service")
    manager = await _manager_of(db, group)

    with pytest.raises(AccessDeniedError):
        await admin_for(db).put_member(
            await _actor(db, manager), group.id, service.id, "member"
        )


async def test_an_admin_groups_holder_can_add_a_service_user(db) -> None:
    group = await make_group(db, "finance")
    service = await make_user(db, "mcp@atlas.internal", role="analyst", kind="service")

    added = await admin_for(db).put_member(
        await actor_with(db), group.id, service.id, "member"
    )

    assert added.user_id == service.id

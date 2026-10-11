# pyright: reportPrivateUsage=false
"""The staged AccessAdmin seams: helpers stage rows under `_write`, and
`_commit` lands several changes with exactly one policy_version bump."""

from typing import Any

import pytest
from sqlmodel import col, select

from app.access.admin import Actor, _utcnow
from app.access.errors import AccessDeniedError
from app.access.models import GroupMember, RbacChange
from app.access.schemas import GrantCreate, UserUpdate
from tests.access_helpers import (
    actor_with,
    add_member,
    admin_for,
    fresh,
    make_group,
    make_user,
    policy_version,
)


def _group_grant(group_id: Any) -> GrantCreate:
    return GrantCreate.model_validate(
        {"subject_type": "group", "subject_id": group_id, "target": "demo/*"}
    )


async def _changes(db) -> list[RbacChange]:
    stmt = select(RbacChange).order_by(col(RbacChange.at))
    return list((await db.execute(stmt)).scalars().all())


async def test_commit_writes_several_changes_with_one_bump(db) -> None:
    admin = admin_for(db)
    actor = Actor.cli()
    group = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    version = await policy_version(db)

    async with admin._write(actor):
        out, member_change = await admin._stage_member(
            actor, group.id, sara.id, "member"
        )
        grant, grant_change = await admin._stage_grant(
            actor, _group_grant(group.id), _utcnow()
        )
        assert member_change is not None
        await admin._commit(member_change, grant_change)

    assert out.user_id == sara.id
    assert grant.target == "demo/*"
    assert await policy_version(db) == version + 1
    assert sorted(c.action for c in await _changes(db)) == [
        "grant.create",
        "member.put",
    ]
    members = (await db.execute(select(GroupMember))).scalars().all()
    assert [(m.group_id, m.user_id) for m in members] == [(group.id, sara.id)]


async def test_staged_noop_member_returns_none(db) -> None:
    admin = admin_for(db)
    actor = Actor.cli()
    group = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    await add_member(db, group, sara)
    version = await policy_version(db)

    async with admin._write(actor):
        out, change = await admin._stage_member(actor, group.id, sara.id, "member")
        assert change is None
        await admin._repo.commit()

    assert out.standing == "member"
    assert await policy_version(db) == version
    assert await _changes(db) == []


async def test_staged_noop_user_update_returns_none(db) -> None:
    admin = admin_for(db)
    actor = Actor.cli()
    sara = await make_user(db, "sara@yougotagift.com", role="viewer")
    version = await policy_version(db)

    async with admin._write(actor):
        user, change = await admin._stage_user_update(
            actor, sara.id, UserUpdate(role="viewer")
        )
        assert change is None
        await admin._repo.commit()

    assert user.role == "viewer"
    assert await policy_version(db) == version
    assert await _changes(db) == []


async def test_stage_helpers_recheck_authority(db) -> None:
    viewer = await actor_with(db, "viewer")
    admin = admin_for(db)
    group = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    version = await policy_version(db)
    viewer = await fresh(db, viewer)
    # A failed write rolls back, expiring loaded rows: hold the ids, not rows.
    group_id, sara_id = group.id, sara.id

    with pytest.raises(AccessDeniedError):
        async with admin._write(viewer):
            await admin._stage_member(viewer, group_id, sara_id, "member")
    with pytest.raises(AccessDeniedError):
        async with admin._write(viewer):
            await admin._stage_grant(viewer, _group_grant(group_id), _utcnow())
    with pytest.raises(AccessDeniedError):
        async with admin._write(viewer):
            await admin._stage_user_update(viewer, sara_id, UserUpdate(role="admin"))

    assert await policy_version(db) == version
    assert await _changes(db) == []

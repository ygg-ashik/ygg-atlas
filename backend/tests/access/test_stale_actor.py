"""Authority is re-checked under the write lock (spec §5.3, write discipline).

An actor's capabilities are judged against the policy resolved at request
start. If access changed before the write takes the lock (another admin
disabled or demoted the actor, say), the write is refused with a 409.
"""

import pytest
from sqlalchemy import func
from sqlmodel import select

from app.access.admin import Actor
from app.access.errors import ConflictError
from app.access.models import RbacChange
from app.access.schemas import GrantCreate, GroupCreate
from tests.access_helpers import (
    actor_with,
    admin_for,
    bump,
    make_group,
    make_user,
    policy_version,
)


async def _change_count(db) -> int:
    return (await db.execute(select(func.count()).select_from(RbacChange))).scalar_one()


async def test_a_stale_actor_is_refused_and_nothing_is_written(db) -> None:
    stale = await actor_with(db)
    victim = await make_user(db, "someone@yougotagift.com")
    victim_id = victim.id
    await bump(db)  # another admin's change landed after the request started
    before = await _change_count(db)
    version = await policy_version(db)

    with pytest.raises(ConflictError, match="Access changed"):
        await admin_for(db).create_grant(
            stale,
            GrantCreate(
                subject_type="user", subject_id=victim_id, target="*", reason="x"
            ),
        )

    assert await _change_count(db) == before
    assert await policy_version(db) == version


async def test_a_stale_actor_is_refused_for_membership_changes(db) -> None:
    stale = await actor_with(db)
    group = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    group_id, sara_id = group.id, sara.id
    await bump(db)
    before = await _change_count(db)

    with pytest.raises(ConflictError):
        await admin_for(db).put_member(stale, group_id, sara_id, "member")

    assert await _change_count(db) == before


async def test_a_fresh_actor_succeeds(db) -> None:
    actor = await actor_with(db)
    before = await _change_count(db)

    await admin_for(db).create_group(actor, GroupCreate(name="growth"))

    assert await _change_count(db) == before + 1


async def test_the_cli_actor_has_no_policy_to_go_stale(db) -> None:
    await bump(db)
    await admin_for(db).create_group(Actor.cli(), GroupCreate(name="growth"))

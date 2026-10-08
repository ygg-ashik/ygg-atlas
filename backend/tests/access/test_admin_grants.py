from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlmodel import col, select

from app.access.admin import Actor
from app.access.cache import PolicyCache
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.models import Group, RbacChange
from app.access.repository import AccessRepository
from app.access.schemas import GrantCreate
from app.access.service import AccessService
from tests.access_helpers import (
    actor_with,
    add_grant,
    add_member,
    admin_for,
    make_group,
    make_user,
    policy_version,
)

REVENUE = "demo/order/revenue"
FUTURE = datetime.now(UTC) + timedelta(days=30)
PAST = datetime.now(UTC) - timedelta(days=1)


def group_grant(group_id: Any, **changes: Any) -> GrantCreate:
    return GrantCreate.model_validate(
        {"subject_type": "group", "subject_id": group_id, "target": "demo/*", **changes}
    )


def direct_user_grant(user_id: Any, **changes: Any) -> GrantCreate:
    return GrantCreate.model_validate(
        {
            "subject_type": "user",
            "subject_id": user_id,
            "target": "demo/*",
            "reason": "x",
            **changes,
        }
    )


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


async def _changes(db) -> list[RbacChange]:
    stmt = select(RbacChange).order_by(col(RbacChange.at))
    return list((await db.execute(stmt)).scalars().all())


async def test_a_group_grant_reaches_members_on_their_next_request(db) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    await add_member(db, group, sara)
    service = AccessService(AccessRepository(db), PolicyCache())
    assert not (await service.policy_for_user(sara.id)).allows(REVENUE)

    await admin_for(db).create_grant(actor, group_grant(group.id))

    assert (await service.policy_for_user(sara.id)).allows(REVENUE)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"target": "demo order"}, "not a resource pattern"),
        ({"target_kind": "clearance", "target": "fields:people_names"}, "clearances"),
        ({"target_kind": "capability", "target": "mcp:use"}, "Groups grant data"),
        ({"expires_at": datetime(2020, 1, 1, tzinfo=UTC)}, "future"),
    ],
)
async def test_invalid_group_grants_are_rejected(
    db, changes: dict[str, Any], message: str
) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "growth")
    with pytest.raises(InvalidChangeError, match=message):
        await admin_for(db).create_grant(actor, group_grant(group.id, **changes))


async def test_user_grants_need_a_reason_and_a_known_capability(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    admin = admin_for(db)

    def user_grant(**fields: Any) -> GrantCreate:
        return GrantCreate.model_validate(
            {"subject_type": "user", "subject_id": sara.id, **fields}
        )

    with pytest.raises(InvalidChangeError, match="reason"):
        await admin.create_grant(actor, user_grant(target="demo/*"))
    with pytest.raises(InvalidChangeError, match="Unknown capability"):
        await admin.create_grant(
            actor,
            user_grant(target_kind="capability", target="root:all", reason="x"),
        )
    grant = await admin.create_grant(
        actor,
        user_grant(
            target_kind="capability",
            target="mcp:use",
            reason="MCP pilot",
            expires_at=FUTURE,
        ),
    )
    assert grant.reason == "MCP pilot"


async def test_duplicate_grants_conflict(db) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "growth")
    admin = admin_for(db)
    await admin.create_grant(actor, group_grant(group.id))
    with pytest.raises(ConflictError):
        await admin.create_grant(actor, group_grant(group.id))


async def test_an_unknown_subject_is_not_found(db) -> None:
    with pytest.raises(NotFoundError):
        await admin_for(db).create_grant(await actor_with(db), group_grant(uuid4()))


async def test_group_grants_need_admin_groups(db) -> None:
    group = await make_group(db, "growth")
    with pytest.raises(AccessDeniedError):
        await admin_for(db).create_grant(
            await actor_with(db, "builder"), group_grant(group.id)
        )


async def test_revoking_records_the_old_grant(db) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "growth")
    admin = admin_for(db)
    grant = await admin.create_grant(actor, group_grant(group.id))
    grant_id, group_id = grant.id, group.id

    await admin.revoke_grant(actor, grant_id)

    assert await admin.list_grants(actor, "group", group_id) == []
    changes = await admin.list_changes(actor)
    assert changes[0].action == "grant.revoke"
    assert changes[0].before is not None
    assert changes[0].before["target"] == "demo/*"


# ---- D10: no self-grants; only capabilities you hold ------------------------


async def test_you_cannot_grant_access_to_yourself(db) -> None:
    actor = await actor_with(db)
    with pytest.raises(AccessDeniedError, match="yourself"):
        await admin_for(db).create_grant(actor, direct_user_grant(actor.user_id))


async def test_the_cli_actor_may_grant_to_any_user_id(db) -> None:
    """D10's self-grant guard only applies to a real actor; the CLI (user_id is
    None) can never equal a grant subject, so it is unaffected."""
    sara = await make_user(db, "sara@yougotagift.com")
    grant = await admin_for(db).create_grant(Actor.cli(), direct_user_grant(sara.id))
    assert grant.subject_id == sara.id


async def test_you_can_only_grant_a_capability_you_hold(db) -> None:
    actor = await _actor_with_capabilities(db, "admin:users")
    sara = await make_user(db, "sara@yougotagift.com")
    with pytest.raises(AccessDeniedError):
        await admin_for(db).create_grant(
            actor,
            direct_user_grant(sara.id, target_kind="capability", target="admin:groups"),
        )


async def test_an_actor_with_only_admin_groups_cannot_make_a_user_grant(db) -> None:
    actor = await _actor_with_capabilities(db, "admin:groups")
    sara = await make_user(db, "sara@yougotagift.com")
    with pytest.raises(AccessDeniedError):
        await admin_for(db).create_grant(actor, direct_user_grant(sara.id))


async def test_an_actor_with_only_admin_users_cannot_make_a_group_grant(db) -> None:
    actor = await _actor_with_capabilities(db, "admin:users")
    group = await make_group(db, "growth")
    with pytest.raises(AccessDeniedError):
        await admin_for(db).create_grant(actor, group_grant(group.id))


async def test_a_grant_for_a_group_in_another_tenant_is_not_found(db) -> None:
    actor = await actor_with(db)
    other = Group(name="eu-team", tenant="acme")
    db.add(other)
    await db.commit()

    with pytest.raises(NotFoundError):
        await admin_for(db).create_grant(actor, group_grant(other.id))


# ---- D10 also covers revoking a deny, which widens access -------------------


async def test_lifting_a_deny_on_yourself_is_denied(db) -> None:
    actor = await actor_with(db)
    assert actor.user_id is not None
    user = await AccessRepository(db).user(actor.user_id)
    assert user is not None
    grant = await add_grant(db, user, "demo/*", effect="deny")
    grant_id = grant.id

    with pytest.raises(AccessDeniedError, match="yourself"):
        await admin_for(db).revoke_grant(actor, grant_id)


async def test_lifting_a_capability_deny_needs_that_capability(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    grant = await add_grant(db, sara, "admin:audit", effect="deny", kind="capability")
    grant_id = grant.id
    actor = await _actor_with_capabilities(db, "admin:users")

    with pytest.raises(AccessDeniedError):
        await admin_for(db).revoke_grant(actor, grant_id)


# ---- fix: an expired duplicate is a distinct, more useful conflict ----------


async def test_an_expired_duplicate_names_the_old_grant(db) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "growth")
    expired = await add_grant(db, group, "demo/*", expires_at=PAST)

    with pytest.raises(ConflictError, match=str(expired.id)):
        await admin_for(db).create_grant(actor, group_grant(group.id))


async def test_a_live_duplicate_keeps_the_generic_message(db) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "growth")
    await add_grant(db, group, "demo/*", expires_at=FUTURE)

    with pytest.raises(ConflictError, match="already exists"):
        await admin_for(db).create_grant(actor, group_grant(group.id))


# ---- fix: revoke_grant hides existence and gates by subject type -----------


async def test_revoking_an_unknown_grant_is_not_found(db) -> None:
    with pytest.raises(NotFoundError):
        await admin_for(db).revoke_grant(await actor_with(db), uuid4())


async def test_revoking_without_any_admin_capability_is_denied(db) -> None:
    actor = await actor_with(db, "builder")
    with pytest.raises(AccessDeniedError, match="admin:groups or admin:users"):
        await admin_for(db).revoke_grant(actor, uuid4())


async def test_revoking_a_group_grant_needs_admin_groups(db) -> None:
    admin_actor = await actor_with(db)
    group = await make_group(db, "growth")
    grant = await admin_for(db).create_grant(admin_actor, group_grant(group.id))
    grant_id = grant.id
    users_only = await _actor_with_capabilities(db, "admin:users")

    with pytest.raises(AccessDeniedError):
        await admin_for(db).revoke_grant(users_only, grant_id)


async def test_revoking_a_cross_tenant_grants_subject_is_not_found(db) -> None:
    actor = await actor_with(db)
    other = Group(name="eu-team", tenant="acme")
    db.add(other)
    await db.commit()
    grant = await add_grant(db, other, "demo/*", bump_version=False)
    grant_id = grant.id
    before = await policy_version(db)

    with pytest.raises(NotFoundError):
        await admin_for(db).revoke_grant(actor, grant_id)

    assert await policy_version(db) == before
    assert (await _changes(db)) == []


# ---- fix: list_grants is gated, as before -----------------------------------


async def test_list_grants_is_gated(db) -> None:
    group = await make_group(db, "growth")
    builder = await actor_with(db, "builder")
    with pytest.raises(AccessDeniedError):
        await admin_for(db).list_grants(builder, "group", group.id)


# ---- reason is trimmed, whitespace-only reason is rejected ------------------


async def test_a_whitespace_only_reason_is_rejected(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    with pytest.raises(InvalidChangeError, match="reason"):
        await admin_for(db).create_grant(
            actor, direct_user_grant(sara.id, reason="   ")
        )


async def test_the_stored_reason_is_stripped(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    grant = await admin_for(db).create_grant(
        actor, direct_user_grant(sara.id, reason="  needs it  ")
    )
    assert grant.reason == "needs it"


# ---- a failed create leaves no trace ----------------------------------------


async def test_a_failed_create_bumps_nothing_and_leaves_the_session_usable(
    db,
) -> None:
    actor = await actor_with(db)
    admin = admin_for(db)
    group = await make_group(db, "growth")
    group_id = group.id  # captured before the failing call expires it
    before = await policy_version(db)

    with pytest.raises(NotFoundError):
        await admin.create_grant(actor, group_grant(uuid4()))

    assert await policy_version(db) == before
    assert await _changes(db) == []
    # the session is still usable for a real write
    grant = await admin.create_grant(actor, group_grant(group_id))
    assert grant.target == "demo/*"

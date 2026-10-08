from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.access.cache import PolicyCache
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.repository import AccessRepository
from app.access.schemas import GrantCreate
from app.access.service import AccessService
from tests.access_helpers import (
    actor_with,
    add_member,
    admin_for,
    make_group,
    make_user,
)

REVENUE = "demo/order/revenue"
FUTURE = datetime.now(UTC) + timedelta(days=30)


def group_grant(group_id: Any, **changes: Any) -> GrantCreate:
    return GrantCreate.model_validate(
        {"subject_type": "group", "subject_id": group_id, "target": "demo/*", **changes}
    )


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
    changes = await admin.list_changes(actor)  # type: ignore[attr-defined]  # arrives in Task 9
    assert changes[0].action == "grant.revoke"
    assert changes[0].before is not None
    assert changes[0].before["target"] == "demo/*"

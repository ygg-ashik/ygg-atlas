"""Resource requests never widen a row scope, and only exact items are requestable."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.errors import InvalidChangeError
from app.access.schemas import AccessRequestCreate, AccessRequestOut, RequestDecision
from app.identity.models import User
from tests.access_helpers import (
    actor_with,
    add_grant,
    add_member,
    fresh,
    make_group,
    make_user,
    policy_of,
    requests_for,
)

REVENUE = "demo/order/revenue"
B2C = {"channel": ["b2c"]}


async def _ask(db: AsyncSession, user: User, target: str) -> AccessRequestOut:
    payload = AccessRequestCreate.model_validate(
        {"kind": "resource", "target": target, "note": "q4"}
    )
    return await requests_for(db).create(await policy_of(db, user), payload)


async def test_an_entity_path_cannot_be_requested(db: AsyncSession) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    with pytest.raises(InvalidChangeError, match="one exact resource"):
        await _ask(db, sara, "demo/order")


async def test_a_resource_already_visible_cannot_be_requested(db: AsyncSession) -> None:
    group = await make_group(db, "uae")
    sara = await make_user(db, "sara@yougotagift.com")
    await add_member(db, group, sara)
    await add_grant(db, group, "demo/*", row_scope=B2C)
    with pytest.raises(InvalidChangeError, match="already see"):
        await _ask(db, sara, REVENUE)


async def test_approval_never_lifts_a_scope_granted_after_the_request(
    db: AsyncSession,
) -> None:
    group = await make_group(db, "uae")
    sara = await make_user(db, "sara@yougotagift.com")
    request = await _ask(db, sara, REVENUE)  # nothing visible yet
    await add_member(db, group, sara)
    await add_grant(db, group, "demo/*", row_scope=B2C)
    admin = await actor_with(db, "admin")
    await requests_for(db).approve(
        await fresh(db, admin), request.id, RequestDecision.model_validate({})
    )
    after = await policy_of(db, sara)
    assert after.row_scope(REVENUE) == ({"channel": frozenset({"b2c"})},)

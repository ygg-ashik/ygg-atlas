from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.access import service as service_module
from app.access.cache import PolicyCache
from app.access.errors import PolicyUnavailableError
from app.access.models import PolicyState
from app.access.repository import AccessRepository
from app.access.service import AccessService
from tests.access_helpers import add_grant, add_member, bump, make_group, make_user

REVENUE = "demo/order/revenue"


def _service(db, clock=None) -> AccessService:
    return AccessService(
        AccessRepository(db), PolicyCache(), clock or (lambda: datetime.now(UTC))
    )


async def test_group_grant_reaches_members(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    group = await make_group(db, "marketing")
    await add_member(db, group, user)
    await add_grant(db, group, "demo/*")

    policy = await _service(db).policy_for_user(user.id)

    assert policy.allows(REVENUE)
    assert policy.has("chat:use")


async def test_policy_is_cached_until_the_version_moves(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    service = _service(db)
    first = await service.policy_for_user(user.id)

    await add_grant(db, user, "demo/*", bump_version=False)
    assert await service.policy_for_user(user.id) is first  # so every write must bump

    await bump(db)
    second = await service.policy_for_user(user.id)
    assert second is not first
    assert second.allows(REVENUE)


async def test_an_expiring_grant_drops_without_a_version_bump(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    expires = datetime.now(UTC) + timedelta(hours=1)
    await add_grant(db, user, "demo/*", expires_at=expires)
    now = [datetime.now(UTC)]
    service = _service(db, clock=lambda: now[0])

    assert (await service.policy_for_user(user.id)).allows(REVENUE)
    now[0] = expires + timedelta(seconds=1)
    assert not (await service.policy_for_user(user.id)).allows(REVENUE)


async def test_unknown_user_is_denied_everything(db) -> None:
    policy = await _service(db).policy_for_user(uuid4())
    assert not policy.active
    assert not policy.has("chat:use")


async def test_missing_policy_state_fails_closed(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    await db.execute(delete(PolicyState))
    await db.commit()
    with pytest.raises(PolicyUnavailableError):
        await _service(db).policy_for_user(user.id)


async def test_evaluator_errors_fail_closed(db, monkeypatch) -> None:
    user = await make_user(db, "sara@yougotagift.com")

    def broken(*_args: object, **_kwargs: object) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(service_module, "evaluate", broken)
    with pytest.raises(PolicyUnavailableError):
        await _service(db).policy_for_user(user.id)

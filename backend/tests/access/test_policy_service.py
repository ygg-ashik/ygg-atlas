from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, text, update
from sqlmodel import col

from app.access import service as service_module
from app.access.cache import PolicyCache
from app.access.errors import PolicyUnavailableError
from app.access.models import Grant, PolicyState
from app.access.repository import AccessRepository
from app.access.service import AccessService, policy_for
from app.database import get_session_factory
from app.identity import Principal
from app.identity.models import User
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


async def test_policy_reads_do_not_reuse_stale_session_rows(db) -> None:
    """Session A must not keep serving an identity-mapped Grant row after
    session B changes it and bumps the version (the fail-open the reviewer
    reproduced: expire_on_commit=False leaves stale rows in A's identity map)."""
    user = await make_user(db, "sara@yougotagift.com")
    grant = await add_grant(db, user, "demo/*")
    service = _service(db)
    assert (await service.policy_for_user(user.id)).allows(REVENUE)

    async with get_session_factory()() as other:
        await other.execute(
            update(Grant).where(col(Grant.id) == grant.id).values(effect="deny")
        )
        await other.commit()
        await bump(other)

    assert not (await service.policy_for_user(user.id)).allows(REVENUE)


async def test_unknown_user_is_not_cached_as_deny_all(db) -> None:
    user_id = uuid4()
    service = _service(db)
    assert not (await service.policy_for_user(user_id)).active

    user = User(id=user_id, email="late@yougotagift.com")
    db.add(user)
    await db.commit()
    await add_grant(db, user, "*", bump_version=False)

    assert (await service.policy_for_user(user_id)).allows(REVENUE)


async def test_policy_for_uses_the_shared_cache(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    principal = Principal(
        user_id=user.id,
        email=user.email,
        display_name="",
        role=user.role,
        kind=user.kind,
        tenant=user.tenant,
        auth_method="dev",
    )

    first = await policy_for(db, principal)
    second = await policy_for(db, principal)
    assert second is first

    await bump(db)
    third = await policy_for(db, principal)
    assert third is not first


async def test_disabled_user_is_denied(db) -> None:
    user = await make_user(db, "sara@yougotagift.com", status="disabled")
    policy = await _service(db).policy_for_user(user.id)
    assert policy.active is False


async def test_a_real_db_failure_fails_closed(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    await db.execute(text("DROP TABLE grants"))
    await db.commit()
    with pytest.raises(PolicyUnavailableError):
        await _service(db).policy_for_user(user.id)

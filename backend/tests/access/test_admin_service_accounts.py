"""AccessAdmin.create_service_account (D13): admin:users, D10 role parity, audited
and versioned like every other access write."""

import pytest

from app.access import AccessAdmin, Actor
from app.access.cache import PolicyCache
from app.access.errors import AccessDeniedError, ConflictError, InvalidChangeError
from app.access.repository import AccessRepository
from app.access.service import AccessService
from app.identity import UserKind
from tests.access_helpers import (
    actor_with,
    add_grant,
    admin_for,
    fresh,
    policy_version,
)


async def _builder_with_admin_users(db) -> Actor:
    base = await actor_with(db, "builder")
    assert base.user_id is not None
    user = await AccessRepository(db).user(base.user_id)
    assert user is not None
    await add_grant(db, user, "admin:users", kind="capability")
    policy = await AccessService(AccessRepository(db), PolicyCache()).policy_for_user(
        user.id
    )
    return Actor.from_policy(policy)


async def test_admin_creates_a_service_account(db) -> None:
    actor = await actor_with(db)
    admin: AccessAdmin = admin_for(db)
    version = await policy_version(db)

    user = await admin.create_service_account(actor, "  Nightly ETL ", "analyst")

    assert user.email == "svc-nightly-etl@atlas.internal"
    assert user.display_name == "Nightly ETL"
    assert user.kind == UserKind.SERVICE
    assert user.role == "analyst"
    assert user.status == "active"
    assert user.owner_user_id == actor.user_id
    assert user.tenant == actor.tenant
    assert await policy_version(db) == version + 1
    change = (await admin.list_changes(actor))[0]
    assert change.action == "service_account.create"
    assert (change.object_type, change.object_id) == ("user", str(user.id))
    assert change.before is None
    assert change.after is not None
    assert change.after["email"] == user.email
    assert (change.actor_user_id, change.via) == (actor.user_id, "api")


async def test_service_account_needs_admin_users(db) -> None:
    actor = await actor_with(db, "analyst")
    with pytest.raises(AccessDeniedError):
        await admin_for(db).create_service_account(actor, "ci deploy", "viewer")


async def test_service_account_role_cannot_exceed_the_actor(db) -> None:
    actor = await _builder_with_admin_users(db)
    admin = admin_for(db)
    with pytest.raises(AccessDeniedError):
        await admin.create_service_account(actor, "ci deploy", "admin")

    created = await admin.create_service_account(actor, "ci deploy", "builder")
    assert created.role == "builder"


async def test_unknown_service_account_role_is_rejected(db) -> None:
    actor = await actor_with(db)
    with pytest.raises(InvalidChangeError, match="Unknown role"):
        await admin_for(db).create_service_account(actor, "ci deploy", "owner")


async def test_duplicate_service_account_conflicts(db) -> None:
    actor = await actor_with(db)
    admin = admin_for(db)
    await admin.create_service_account(actor, "CI deploy", "viewer")
    version = await policy_version(db)

    with pytest.raises(ConflictError):
        await admin.create_service_account(
            await fresh(db, actor), "ci-deploy", "viewer"
        )
    assert await policy_version(db) == version


@pytest.mark.parametrize("name", ["", "ab", "!!!", "x" * 41, "é√ß"])
async def test_bad_service_account_names(db, name: str) -> None:
    actor = await actor_with(db)
    version = await policy_version(db)
    with pytest.raises(InvalidChangeError):
        await admin_for(db).create_service_account(actor, name, "viewer")
    assert await policy_version(db) == version


async def test_cli_actor_may_create_one(db) -> None:
    admin = admin_for(db)
    user = await admin.create_service_account(Actor.cli(), "reports", "admin")

    assert user.owner_user_id is None
    assert user.role == "admin"
    change = (await admin.list_changes(Actor.cli()))[0]
    assert (change.action, change.via, change.actor_user_id) == (
        "service_account.create",
        "cli",
        None,
    )

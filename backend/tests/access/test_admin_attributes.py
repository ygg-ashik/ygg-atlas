"""User attributes through AccessAdmin (D3.5, C11)."""

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
from app.access.models import RbacChange
from app.access.repository import AccessRepository
from app.access.schemas import GrantCreate
from app.access.service import AccessService
from app.identity.models import User
from tests.access_helpers import (
    actor_with,
    admin_for,
    fresh,
    make_group,
    make_user,
    mirror_dimensions,
    policy_version,
)

REVENUE = "demo/order/revenue"


async def _changes(db, action: str) -> list[RbacChange]:
    stmt = select(RbacChange).where(col(RbacChange.action) == action)
    return list((await db.execute(stmt)).scalars().all())


async def test_set_overwrite_and_delete_are_audited_and_each_bumps(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    admin = admin_for(db)

    start = await policy_version(db)
    row = await admin.set_attribute(await fresh(db, actor), sara.id, "rep_name", "Ali")
    assert (row.key, row.value, row.set_by) == ("rep_name", "Ali", actor.user_id)
    assert await policy_version(db) == start + 1

    await admin.set_attribute(await fresh(db, actor), sara.id, "rep_name", "Ali K")
    assert await policy_version(db) == start + 2

    await admin.delete_attribute(await fresh(db, actor), sara.id, "rep_name")
    assert await policy_version(db) == start + 3
    assert await admin.list_attributes(await fresh(db, actor), sara.id) == []

    sets = await _changes(db, "attribute.set")
    assert [(c.before, c.after) for c in sets] == [
        (None, {"key": "rep_name", "value": "Ali"}),
        ({"key": "rep_name", "value": "Ali"}, {"key": "rep_name", "value": "Ali K"}),
    ]
    assert all(c.object_type == "user_attribute" for c in sets)
    assert sets[0].object_id == f"{sara.id}:rep_name"
    (deleted,) = await _changes(db, "attribute.delete")
    assert (deleted.before, deleted.after) == (
        {"key": "rep_name", "value": "Ali K"},
        None,
    )


async def test_a_no_op_set_does_not_bump(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    admin = admin_for(db)
    await admin.set_attribute(await fresh(db, actor), sara.id, "rep_name", "Ali")
    before = await policy_version(db)

    await admin.set_attribute(await fresh(db, actor), sara.id, "rep_name", "Ali")

    assert await policy_version(db) == before
    assert len(await _changes(db, "attribute.set")) == 1


async def test_an_attribute_change_reaches_a_cached_scoped_policy(db) -> None:
    """`$self` resolves through the attribute, so a write must refresh the policy."""
    await mirror_dimensions(
        db, [("demo", "order", "sales_rep", "rep_name")], bump_version=False
    )
    actor = await actor_with(db)
    group = await make_group(db, "sales")
    sara = await make_user(db, "sara@yougotagift.com")
    admin = admin_for(db)
    await admin.put_member(await fresh(db, actor), group.id, sara.id, "member")
    await admin.create_grant(
        await fresh(db, actor),
        GrantCreate.model_validate(
            {
                "subject_type": "group",
                "subject_id": group.id,
                "target": "demo/*",
                "row_scope": {"sales_rep": ["$self"]},
            }
        ),
    )
    service = AccessService(AccessRepository(db), PolicyCache())
    cached = await service.policy_for_user(sara.id)
    assert cached.row_scope(REVENUE) == ()  # $self unresolved: skipped

    await admin.set_attribute(await fresh(db, actor), sara.id, "rep_name", "Ali")
    refreshed = await service.policy_for_user(sara.id)
    assert refreshed.policy_version == cached.policy_version + 1
    assert refreshed.row_scope(REVENUE) == ({"sales_rep": frozenset({"Ali"})},)

    await admin.delete_attribute(await fresh(db, actor), sara.id, "rep_name")
    after_delete = await service.policy_for_user(sara.id)
    assert after_delete.policy_version == refreshed.policy_version + 1
    assert after_delete.row_scope(REVENUE) == ()


async def test_nobody_sets_their_own_attributes(db) -> None:
    actor = await actor_with(db)
    assert actor.user_id is not None
    admin = admin_for(db)
    with pytest.raises(ConflictError, match="your own"):
        await admin.set_attribute(actor, actor.user_id, "rep_name", "Me")
    with pytest.raises(ConflictError, match="your own"):
        await admin.delete_attribute(actor, actor.user_id, "rep_name")


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("email", "x@yougotagift.com", "built in"),
        ("user_id", "x", "built in"),
        ("Rep", "x", "key"),
        ("1rep", "x", "key"),
        ("rep-name", "x", "key"),
        ("r" * 65, "x", "key"),
        ("rep_name", "", "value"),
        ("rep_name", "   ", "value"),
        ("rep_name", "x" * 201, "value"),
    ],
)
async def test_bad_keys_and_values_are_rejected(
    db, key: str, value: str, message: str
) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    with pytest.raises(InvalidChangeError, match=message):
        await admin_for(db).set_attribute(await fresh(db, actor), sara.id, key, value)


async def test_attribute_writes_need_admin_users(db) -> None:
    actor = await actor_with(db, "builder")
    sara = await make_user(db, "sara@yougotagift.com")
    admin = admin_for(db)
    actor = await fresh(db, actor)
    with pytest.raises(AccessDeniedError, match="admin:users"):
        await admin.set_attribute(actor, sara.id, "rep_name", "Ali")
    with pytest.raises(AccessDeniedError, match="admin:users"):
        await admin.delete_attribute(actor, sara.id, "rep_name")
    with pytest.raises(AccessDeniedError, match="admin:users"):
        await admin.list_attributes(actor, sara.id)


async def test_a_user_in_another_tenant_is_not_found(db) -> None:
    actor = await actor_with(db)
    other = User(email=f"{uuid4().hex[:8]}@yougotagift.com", tenant="other")
    other_id = other.id  # read before the commit expires the instance
    db.add(other)
    await db.commit()
    admin = admin_for(db)
    with pytest.raises(NotFoundError):
        await admin.set_attribute(await fresh(db, actor), other_id, "rep_name", "Ali")
    with pytest.raises(NotFoundError):
        await admin.list_attributes(await fresh(db, actor), other_id)


async def test_deleting_a_missing_attribute_is_not_found(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    before = await policy_version(db)
    with pytest.raises(NotFoundError):
        await admin_for(db).delete_attribute(
            await fresh(db, actor), sara.id, "rep_name"
        )
    assert await policy_version(db) == before


async def test_list_attributes_is_sorted_and_the_cli_may_write(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    admin = admin_for(db)
    await admin.set_attribute(Actor.cli(), sara.id, "rep_name", "Ali")
    await admin.set_attribute(Actor.cli(), sara.id, "csm_name", "Ali K")

    rows = await admin.list_attributes(Actor.cli(), sara.id)

    assert [(r.key, r.value) for r in rows] == [
        ("csm_name", "Ali K"),
        ("rep_name", "Ali"),
    ]
    assert all(r.set_by is None for r in rows)

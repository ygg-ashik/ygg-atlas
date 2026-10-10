"""Label-class mask settings and the scope-dimension listing (D3.9, C12, D3.6)."""

import pytest
from sqlmodel import col, select

from app.access.admin import Actor
from app.access.cache import PolicyCache
from app.access.catalog import ADMIN_GROUPS, ADMIN_USERS
from app.access.errors import AccessDeniedError, InvalidChangeError
from app.access.models import RbacChange
from app.access.repository import AccessRepository
from app.access.service import AccessService
from tests.access_helpers import (
    actor_with,
    add_grant,
    admin_for,
    fresh,
    make_user,
    mirror_dimensions,
    policy_version,
    seed_label_classes,
)


async def _actor_with_capabilities(db, *capabilities: str) -> Actor:
    base = await actor_with(db, "builder")
    assert base.user_id is not None
    user = await AccessRepository(db).user(base.user_id)
    assert user is not None
    for capability in capabilities:
        await add_grant(db, user, capability, kind="capability")
    return await fresh(db, base)


async def test_set_label_class_is_audited_bumps_and_reaches_a_cached_policy(
    db,
) -> None:
    await seed_label_classes(db)
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    service = AccessService(AccessRepository(db), PolicyCache())
    cached = await service.policy_for_user(sara.id)
    stored = cached.mask_mode("person_name")
    assert stored is not None
    assert stored.mode == "suppress"

    row = await admin_for(db).set_label_class(
        await fresh(db, actor), "person_name", "bucket", 3
    )

    assert (row.mode, row.bucket_size) == ("bucket", 3)
    refreshed = await service.policy_for_user(sara.id)
    assert refreshed.policy_version == cached.policy_version + 1
    mode = refreshed.mask_mode("person_name")
    assert mode is not None
    assert (mode.mode, mode.bucket_size) == ("bucket", 3)
    (change,) = (
        await db.execute(
            select(RbacChange).where(col(RbacChange.action) == "label_class.update")
        )
    ).scalars()
    assert change.object_type == "label_class"
    assert change.object_id == "person_name"
    assert change.before == {
        "label_class": "person_name",
        "mode": "suppress",
        "bucket_size": 5,
    }
    assert change.after == {
        "label_class": "person_name",
        "mode": "bucket",
        "bucket_size": 3,
    }


async def test_a_missing_row_is_created_and_bucket_size_defaults(db) -> None:
    actor = await actor_with(db)
    row = await admin_for(db).set_label_class(actor, "business_name", "pseudonymise")
    assert (row.label_class, row.mode, row.bucket_size) == (
        "business_name",
        "pseudonymise",
        5,
    )


async def test_an_omitted_bucket_size_keeps_the_stored_one(db) -> None:
    await seed_label_classes(db, bucket=7)
    actor = await actor_with(db)
    row = await admin_for(db).set_label_class(actor, "person_name", "bucket")
    assert row.bucket_size == 7


async def test_a_no_op_label_class_write_does_not_bump(db) -> None:
    await seed_label_classes(db)
    actor = await actor_with(db)
    before = await policy_version(db)
    await admin_for(db).set_label_class(actor, "person_name", "suppress", 5)
    assert await policy_version(db) == before


@pytest.mark.parametrize(
    ("label_class", "mode", "bucket_size", "message"),
    [
        ("category", "suppress", None, "category"),
        ("salary", "suppress", None, "salary"),
        ("person_name", "hide", None, "hide"),
        ("person_name", "bucket", 0, "1 and 50"),
        ("person_name", "bucket", 51, "1 and 50"),
    ],
)
async def test_bad_label_class_settings_are_rejected(
    db, label_class: str, mode: str, bucket_size: int | None, message: str
) -> None:
    actor = await actor_with(db)
    with pytest.raises(InvalidChangeError, match=message):
        await admin_for(db).set_label_class(actor, label_class, mode, bucket_size)


async def test_label_classes_need_admin_groups(db) -> None:
    actor = await _actor_with_capabilities(db, ADMIN_USERS)
    admin = admin_for(db)
    with pytest.raises(AccessDeniedError, match="admin:groups"):
        await admin.set_label_class(actor, "person_name", "suppress")
    with pytest.raises(AccessDeniedError, match="admin:groups"):
        await admin.list_label_classes(actor)


async def test_list_label_classes_returns_both_maskable_classes(db) -> None:
    await seed_label_classes(db)
    actor = await actor_with(db)
    rows = await admin_for(db).list_label_classes(actor)
    assert [(r.label_class, r.mode) for r in rows] == [
        ("business_name", "pseudonymise"),
        ("person_name", "suppress"),
    ]


async def test_an_unset_label_class_lists_as_suppressed(db) -> None:
    """A missing row means suppress (fail closed, C17); the listing says so."""
    actor = await actor_with(db)
    rows = await admin_for(db).list_label_classes(actor)
    assert [(r.label_class, r.mode) for r in rows] == [
        ("business_name", "suppress"),
        ("person_name", "suppress"),
    ]


# ---- scope dimensions -------------------------------------------------------


async def test_scope_dimensions_list_with_either_admin_capability(db) -> None:
    await mirror_dimensions(
        db,
        [
            ("demo", "order", "sales_rep", "rep_name"),
            ("demo", "order", "channel", None),
        ],
        bump_version=False,
    )
    admin = admin_for(db)
    for capability in (ADMIN_GROUPS, ADMIN_USERS):
        actor = await _actor_with_capabilities(db, capability)
        rows = await admin.list_scope_dimensions(actor)
        assert [(r.entity, r.dimension, r.self_attribute) for r in rows] == [
            ("order", "channel", None),
            ("order", "sales_rep", "rep_name"),
        ]


async def test_scope_dimensions_need_an_admin_capability(db) -> None:
    actor = await actor_with(db, "builder")
    with pytest.raises(AccessDeniedError):
        await admin_for(db).list_scope_dimensions(actor)

"""Scoped grants and clearance grants through AccessAdmin (D3.3, D3.6, C10)."""

from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlmodel import col, select

from app.access.admin import Actor
from app.access.cache import PolicyCache
from app.access.catalog import CLEARANCE_BUSINESS_NAMES, CLEARANCE_PEOPLE_NAMES
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
)
from app.access.facts import (
    MAX_SCOPE_DIMENSIONS,
    MAX_SCOPE_VALUES,
    is_well_formed_scope,
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
    fresh,
    make_group,
    make_user,
    mirror_dimensions,
    policy_version,
)

REVENUE = "demo/order/revenue"
MIRROR: list[tuple[str, str, str, str | None]] = [
    ("demo", "order", "channel", None),
    ("demo", "order", "sales_rep", "rep_name"),
    ("demo", "customer", "segment", None),
    ("deepsales", "ds_task", "csm", "csm_name"),
]


def scoped(
    subject_id: UUID, target: str, row_scope: Any, **changes: Any
) -> GrantCreate:
    return GrantCreate.model_validate(
        {
            "subject_type": "group",
            "subject_id": subject_id,
            "target": target,
            "row_scope": row_scope,
            **changes,
        }
    )


async def _setup(db) -> tuple[Actor, UUID]:
    await mirror_dimensions(db, MIRROR, bump_version=False)
    actor = await actor_with(db)
    group = await make_group(db, "sales")
    return actor, group.id


# ---- schema shape (the API's first line) ---------------------------------


@pytest.mark.parametrize(
    "row_scope",
    [
        {},
        {"channel": "b2c"},
        {"channel": []},
        {"channel": [""]},
        {"channel": [1]},
        {"Channel": ["b2c"]},
        {"1channel": ["b2c"]},
        {"chan-nel": ["b2c"]},
        {f"d{i}": ["x"] for i in range(MAX_SCOPE_DIMENSIONS + 1)},
        {"channel": [f"v{i}" for i in range(MAX_SCOPE_VALUES + 1)]},
        {"channel": ["x" * 201]},
        {"channel": ["   "]},
        {"c" * 65: ["b2c"]},
        ["channel"],
        "channel=b2c",
    ],
)
def test_the_schema_rejects_every_malformed_scope(row_scope: Any) -> None:
    with pytest.raises(ValidationError):
        scoped(UUID(int=1), "demo/*", row_scope)


ACCEPTED: list[dict[str, list[str]]] = [
    {"channel": ["b2c"]},
    {"channel": ["b2c", "b2b", "b2c"]},
    {"sales_rep": ["$self"]},
    {"csm": ["$self", "Alice"], "country": ["AE", "SA"]},
    {f"d{i}": ["x"] for i in range(MAX_SCOPE_DIMENSIONS)},
    {"channel": [f"v{i}" for i in range(MAX_SCOPE_VALUES)]},
    {"channel": ["x" * 200]},
    {"c" * 64: ["b2c"]},
]


@pytest.mark.parametrize("row_scope", ACCEPTED)
def test_every_scope_the_schema_accepts_is_well_formed_for_the_evaluator(
    row_scope: dict[str, list[str]],
) -> None:
    stored = scoped(UUID(int=1), "demo/*", row_scope).row_scope
    assert stored is not None
    assert is_well_formed_scope(stored)


def test_the_schema_strips_values() -> None:
    payload = scoped(UUID(int=1), "demo/*", {"channel": [" b2c ", "b2c"]})
    assert payload.row_scope == {"channel": ["b2c"]}


def test_the_evaluator_rejects_an_overlong_dimension_key() -> None:
    assert not is_well_formed_scope({"c" * 65: ["b2c"]})
    assert is_well_formed_scope({"c" * 64: ["b2c"]})


def test_the_schema_dedupes_and_sorts_values() -> None:
    payload = scoped(UUID(int=1), "demo/*", {"channel": ["b2c", "b2b", "b2c"]})
    assert payload.row_scope == {"channel": ["b2b", "b2c"]}


# ---- create_grant validation against the mirror -------------------------


@pytest.mark.parametrize(
    ("target", "row_scope", "changes", "message"),
    [
        ("demo/*", {"channel": ["b2c"]}, {"effect": "deny"}, "deny"),
        (
            "fields:people_names",
            {"channel": ["b2c"]},
            {"target_kind": "clearance"},
            "data",
        ),
        ("demo/order/*", {"segment": ["vip"]}, {}, "segment"),
        ("*", {"region": ["AE"]}, {}, "region"),
        ("demo/order/*", {"channel": ["$self"]}, {}, r"\$self"),
        ("ga4/*", {"channel": ["b2c"]}, {}, "ga4"),
        ("demo/checkout/*", {"channel": ["b2c"]}, {}, "demo/checkout"),
    ],
)
async def test_invalid_scoped_grants_are_rejected(
    db, target: str, row_scope: Any, changes: dict[str, Any], message: str
) -> None:
    actor, group_id = await _setup(db)
    before = await policy_version(db)
    with pytest.raises(InvalidChangeError, match=message):
        await admin_for(db).create_grant(
            actor, scoped(group_id, target, row_scope, **changes)
        )
    assert await policy_version(db) == before


async def test_a_scope_on_a_capability_grant_is_rejected(db) -> None:
    actor, _ = await _setup(db)
    sara = await make_user(db, "sara@yougotagift.com")
    payload = GrantCreate.model_validate(
        {
            "subject_type": "user",
            "subject_id": sara.id,
            "target_kind": "capability",
            "target": "mcp:use",
            "reason": "pilot",
            "row_scope": {"channel": ["b2c"]},
        }
    )
    with pytest.raises(InvalidChangeError, match="data"):
        await admin_for(db).create_grant(await fresh(db, actor), payload)


async def test_a_scope_bypassing_the_schema_is_still_rejected(db) -> None:
    actor, group_id = await _setup(db)
    payload = GrantCreate.model_construct(
        subject_type="group",
        subject_id=group_id,
        effect="allow",
        target_kind="resource",
        target="demo/*",
        reason="",
        expires_at=None,
        row_scope={"channel": []},
    )
    with pytest.raises(InvalidChangeError, match="scope"):
        await admin_for(db).create_grant(actor, payload)


@pytest.mark.parametrize(
    ("target", "row_scope"),
    [
        ("*", {"channel": ["b2c"]}),
        ("demo/*", {"channel": ["b2c"], "segment": ["vip"]}),
        (REVENUE, {"sales_rep": ["$self"]}),
        ("demo/*/revenue", {"channel": ["b2c"]}),
        ("deepsales/ds_task/*", {"csm": ["$self"]}),
    ],
)
async def test_valid_scoped_grants_are_stored_and_audited(
    db, target: str, row_scope: dict[str, list[str]]
) -> None:
    actor, group_id = await _setup(db)
    before = await policy_version(db)

    grant = await admin_for(db).create_grant(actor, scoped(group_id, target, row_scope))

    assert grant.row_scope == row_scope
    assert await policy_version(db) == before + 1
    stored = await AccessRepository(db).grant(grant.id)
    assert stored is not None
    assert stored.row_scope == row_scope
    change = (
        await db.execute(
            select(RbacChange).where(col(RbacChange.action) == "grant.create")
        )
    ).scalar_one()
    assert change.after is not None
    assert change.after["row_scope"] == row_scope


async def test_a_scoped_grant_reaches_a_cached_policy(db) -> None:
    actor, group_id = await _setup(db)
    sara = await make_user(db, "sara@yougotagift.com")
    group = await db.get(Group, group_id)
    assert group is not None
    await add_member(db, group, sara)
    actor = await fresh(db, actor)
    service = AccessService(AccessRepository(db), PolicyCache())
    cached = await service.policy_for_user(sara.id)
    assert not cached.allows(REVENUE)

    await admin_for(db).create_grant(
        actor, scoped(group_id, "demo/*", {"channel": ["b2c"]})
    )

    refreshed = await service.policy_for_user(sara.id)
    assert refreshed.policy_version == cached.policy_version + 1
    assert refreshed.row_scope(REVENUE) == ({"channel": frozenset({"b2c"})},)


async def test_a_scoped_and_an_unscoped_allow_on_one_target_conflict(db) -> None:
    actor, group_id = await _setup(db)
    admin = admin_for(db)
    await admin.create_grant(actor, scoped(group_id, "demo/*", None))
    with pytest.raises(ConflictError):
        await admin.create_grant(
            await fresh(db, actor), scoped(group_id, "demo/*", {"channel": ["b2c"]})
        )


async def test_a_scoped_grant_on_an_unmirrored_plugin_is_rejected(db) -> None:
    """A disabled plugin is not mirrored, so nothing under it can be scoped."""
    await mirror_dimensions(db, [], bump_version=False)
    actor = await actor_with(db)
    group = await make_group(db, "sales")
    with pytest.raises(InvalidChangeError, match="scoped"):
        await admin_for(db).create_grant(
            actor, scoped(group.id, "demo/*", {"channel": ["b2c"]})
        )


# ---- clearance grants (C10) ---------------------------------------------


async def _cleared_admin(db, *clearances: str) -> Actor:
    base = await actor_with(db)
    assert base.user_id is not None
    user = await AccessRepository(db).user(base.user_id)
    assert user is not None
    for clearance in clearances:
        await add_grant(db, user, clearance, kind="clearance")
    return await fresh(db, base)


def clearance(subject_type: str, subject_id: UUID, code: str, **changes: Any):
    return GrantCreate.model_validate(
        {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "target_kind": "clearance",
            "target": code,
            "reason": "needs names",
            **changes,
        }
    )


async def test_a_cleared_admin_grants_a_clearance_to_a_group_and_a_user(db) -> None:
    actor = await _cleared_admin(db, CLEARANCE_PEOPLE_NAMES)
    group = await make_group(db, "csm")
    sara = await make_user(db, "sara@yougotagift.com")
    actor = await fresh(db, actor)
    admin = admin_for(db)
    service = AccessService(AccessRepository(db), PolicyCache())
    assert not (await service.policy_for_user(sara.id)).has_clearance(
        CLEARANCE_PEOPLE_NAMES
    )

    await admin.create_grant(
        actor, clearance("group", group.id, CLEARANCE_PEOPLE_NAMES)
    )
    await admin.create_grant(
        await fresh(db, actor), clearance("user", sara.id, CLEARANCE_PEOPLE_NAMES)
    )

    assert (await service.policy_for_user(sara.id)).has_clearance(
        CLEARANCE_PEOPLE_NAMES
    )


async def test_an_unknown_clearance_is_rejected(db) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "csm")
    with pytest.raises(InvalidChangeError, match="Unknown clearance"):
        await admin_for(db).create_grant(
            actor, clearance("group", group.id, "fields:salaries")
        )


async def test_an_api_actor_cannot_grant_a_clearance_they_lack(db) -> None:
    actor = await _cleared_admin(db, CLEARANCE_BUSINESS_NAMES)
    group = await make_group(db, "csm")
    with pytest.raises(AccessDeniedError, match="clearance"):
        await admin_for(db).create_grant(
            await fresh(db, actor), clearance("group", group.id, CLEARANCE_PEOPLE_NAMES)
        )


async def test_a_clearance_deny_needs_no_clearance(db) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "csm")
    grant = await admin_for(db).create_grant(
        await fresh(db, actor),
        clearance("group", group.id, CLEARANCE_PEOPLE_NAMES, effect="deny"),
    )
    assert grant.effect == "deny"


async def test_revoking_a_clearance_deny_needs_the_clearance(db) -> None:
    group = await make_group(db, "csm")
    deny = await add_grant(
        db, group, CLEARANCE_PEOPLE_NAMES, kind="clearance", effect="deny"
    )
    uncleared = await actor_with(db)
    with pytest.raises(AccessDeniedError, match="clearance"):
        await admin_for(db).revoke_grant(uncleared, deny.id)

    cleared = await _cleared_admin(db, CLEARANCE_PEOPLE_NAMES)
    await admin_for(db).revoke_grant(cleared, deny.id)
    assert await AccessRepository(db).grant(deny.id) is None


async def test_revoking_a_clearance_allow_needs_no_clearance(db) -> None:
    group = await make_group(db, "csm")
    allow = await add_grant(db, group, CLEARANCE_PEOPLE_NAMES, kind="clearance")
    actor = await actor_with(db)
    await admin_for(db).revoke_grant(actor, allow.id)
    assert await AccessRepository(db).grant(allow.id) is None


async def test_the_cli_grants_and_lifts_clearances_without_holding_them(db) -> None:
    group = await make_group(db, "csm")
    admin = admin_for(db)
    grant = await admin.create_grant(
        Actor.cli(), clearance("group", group.id, CLEARANCE_PEOPLE_NAMES)
    )
    assert grant.target == CLEARANCE_PEOPLE_NAMES
    deny = await add_grant(
        db, group, CLEARANCE_BUSINESS_NAMES, kind="clearance", effect="deny"
    )
    await admin.revoke_grant(Actor.cli(), deny.id)
    assert await AccessRepository(db).grant(deny.id) is None

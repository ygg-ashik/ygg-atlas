"""Access requests: create, cancel, list own, options, and the decidable scope."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func
from sqlmodel import select

from app.access import Actor
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.facts import GrantFacts, GroupFacts
from app.access.models import AccessRequest, Group, RbacChange
from app.access.policy import Policy, decidable_scope
from app.access.repositories import RequestRepository
from app.access.schemas import AccessRequestCreate, RequestDecision
from app.access.services import groups_granting
from tests.access_helpers import (
    actor_with,
    add_grant,
    add_member,
    make_group,
    make_user,
    policy_of,
    policy_version,
    requests_for,
)

REVENUE = "demo/order/revenue"
NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def _ask(
    kind: str, target: str, note: str = "for the Q4 review"
) -> AccessRequestCreate:
    return AccessRequestCreate.model_validate(
        {"kind": kind, "target": target, "note": note}
    )


async def _rbac_count(db) -> int:
    return (await db.execute(select(func.count()).select_from(RbacChange))).one()[0]


# ---- create and read back ---------------------------------------------------


async def test_a_viewer_with_no_groups_requests_a_resource_and_reads_it_back(
    db,
) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    service = requests_for(db)

    out = await service.create(await policy_of(db, sara), _ask("resource", REVENUE))

    assert out.status == "pending"
    assert out.kind == "resource"
    assert out.target == REVENUE
    assert out.target_label == REVENUE
    assert out.note == "for the Q4 review"
    assert out.decided_by is None
    assert out.requester is None
    own = await service.list_own(await policy_of(db, sara))
    assert [r.id for r in own] == [out.id]


async def test_a_disabled_user_cannot_create_or_list(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com", status="disabled")
    service = requests_for(db)
    policy = await policy_of(db, sara)

    with pytest.raises(AccessDeniedError):
        await service.create(policy, _ask("resource", REVENUE))
    with pytest.raises(AccessDeniedError):
        await service.list_own(policy)
    with pytest.raises(AccessDeniedError):
        await service.options(policy, REVENUE)


async def test_a_note_is_stripped_and_a_blank_note_is_rejected(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    service = requests_for(db)

    with pytest.raises(InvalidChangeError):
        await service.create(await policy_of(db, sara), _ask("resource", REVENUE, " "))
    out = await service.create(
        await policy_of(db, sara), _ask("resource", REVENUE, "  why \n")
    )
    assert out.note == "why"


async def test_group_request_needs_a_group_in_the_tenant(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    other = Group(name="elsewhere", tenant="other")
    db.add(other)
    await db.commit()
    service = requests_for(db)
    policy = await policy_of(db, sara)

    for target in (str(uuid4()), str(other.id), "growth"):
        with pytest.raises(InvalidChangeError):
            await service.create(policy, _ask("group", target))


async def test_group_request_stores_the_canonical_id_and_labels_it(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    growth = await make_group(db, "growth")

    out = await requests_for(db).create(
        await policy_of(db, sara), _ask("group", str(growth.id).upper())
    )

    assert out.target == str(growth.id)
    assert out.target_label == "growth"


async def test_group_request_refused_when_already_a_member(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    growth = await make_group(db, "growth")
    await add_member(db, growth, sara)

    with pytest.raises(InvalidChangeError):
        await requests_for(db).create(
            await policy_of(db, sara), _ask("group", str(growth.id))
        )


async def test_role_request_must_be_strictly_above_current_role(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com", role="analyst")
    service = requests_for(db)
    policy = await policy_of(db, sara)

    for target in ("viewer", "analyst", "superuser"):
        with pytest.raises(InvalidChangeError):
            await service.create(policy, _ask("role", target))
    out = await service.create(policy, _ask("role", "builder"))
    assert out.target_label == "builder"


async def test_resource_request_needs_a_full_resource_path(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    service = requests_for(db)
    policy = await policy_of(db, sara)

    for target in ("demo/*", "demo", "demo//x", "Demo/Order"):
        with pytest.raises(InvalidChangeError):
            await service.create(policy, _ask("resource", target))


async def test_duplicate_pending_request_is_409(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    service = requests_for(db)
    await service.create(await policy_of(db, sara), _ask("resource", REVENUE))

    with pytest.raises(ConflictError, match="already asked"):
        await service.create(await policy_of(db, sara), _ask("resource", REVENUE))


async def test_partial_index_violation_maps_to_409(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    service = requests_for(db)
    # A failed write rolls back, expiring loaded rows: hold the policy, not sara.
    policy = await policy_of(db, sara)
    await service.create(policy, _ask("resource", REVENUE))

    async def no_pending(*_args: object) -> None:
        return None

    monkeypatch.setattr(RequestRepository, "pending_request", no_pending)
    with pytest.raises(ConflictError, match="already asked"):
        await service.create(policy, _ask("resource", REVENUE))
    # The session is usable again after the mapped failure.
    assert len(await service.list_own(policy)) == 1


async def test_twenty_pending_cap(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    service = requests_for(db)
    policy = await policy_of(db, sara)
    made = [
        await service.create(policy, _ask("resource", f"demo/order/m{i}"))
        for i in range(20)
    ]

    with pytest.raises(InvalidChangeError, match="20"):
        await service.create(policy, _ask("resource", "demo/order/m20"))
    await service.cancel(policy, made[0].id)
    out = await service.create(policy, _ask("resource", "demo/order/m20"))
    assert out.status == "pending"


async def test_cancel_by_requester_only(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    omar = await make_user(db, "omar@yougotagift.com")
    service = requests_for(db)
    mine = await service.create(await policy_of(db, sara), _ask("resource", REVENUE))

    with pytest.raises(NotFoundError):
        await service.cancel(await policy_of(db, omar), mine.id)
    with pytest.raises(NotFoundError):
        await service.cancel(await policy_of(db, sara), uuid4())
    cancelled = await service.cancel(await policy_of(db, sara), mine.id)
    assert cancelled.status == "cancelled"
    assert cancelled.decided_at is not None
    with pytest.raises(ConflictError):
        await service.cancel(await policy_of(db, sara), mine.id)


async def test_cancel_of_a_decided_request_is_409(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    service = requests_for(db)
    mine = await service.create(await policy_of(db, sara), _ask("resource", REVENUE))
    await service.decline(Actor.cli(), mine.id, RequestDecision())

    with pytest.raises(ConflictError):
        await service.cancel(await policy_of(db, sara), mine.id)


async def test_create_cancel_decline_write_no_rbac_changes_and_no_bump(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    admin = await actor_with(db, "admin")
    service = requests_for(db)
    version = await policy_version(db)
    changes = await _rbac_count(db)
    policy = await policy_of(db, sara)

    first = await service.create(policy, _ask("resource", REVENUE))
    await service.cancel(policy, first.id)
    second = await service.create(policy, _ask("resource", "demo/order/count"))
    declined = await service.decline(
        admin, second.id, RequestDecision(note="not this quarter")
    )

    assert declined.status == "declined"
    assert declined.decision_note == "not this quarter"
    assert declined.decided_by is not None
    assert declined.decided_by.user_id == admin.user_id
    assert await policy_version(db) == version
    assert await _rbac_count(db) == changes


async def test_list_own_is_newest_first_and_only_mine(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    omar = await make_user(db, "omar@yougotagift.com")
    service = requests_for(db)
    first = await service.create(await policy_of(db, sara), _ask("resource", REVENUE))
    await service.create(await policy_of(db, omar), _ask("resource", REVENUE))
    second = await service.create(
        await policy_of(db, sara), _ask("resource", "demo/order/count")
    )

    own = await service.list_own(await policy_of(db, sara))

    assert [r.id for r in own] == [second.id, first.id]


# ---- options ----------------------------------------------------------------


async def test_options_lists_groups_holding_the_resource(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    finance = await make_group(db, "finance")
    payments = await make_group(db, "payments", parent=finance)
    direct = await make_group(db, "direct")
    await make_group(db, "unrelated")
    await add_grant(db, finance, "demo/*")
    await add_grant(db, direct, REVENUE)

    out = await requests_for(db).options(await policy_of(db, sara), REVENUE)

    assert out.resource == REVENUE
    assert [g.name for g in out.groups] == ["direct", "finance", "payments"]
    assert {g.id for g in out.groups} == {finance.id, payments.id, direct.id}
    assert out.can_request_resource is True


async def test_options_excludes_member_groups_and_deny_matched_groups(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    mine = await make_group(db, "mine")
    await add_member(db, mine, sara)
    denied = await make_group(db, "denied")
    parent_denied = await make_group(db, "parent-denied")
    child = await make_group(db, "child", parent=parent_denied)
    expired_allow = await make_group(db, "expired-allow")
    expired_deny = await make_group(db, "expired-deny")
    past = datetime.now(UTC) - timedelta(days=1)
    for group in (mine, denied, child, expired_deny):
        await add_grant(db, group, "demo/*")
    await add_grant(db, denied, REVENUE, effect="deny")
    await add_grant(db, parent_denied, "demo/order/*", effect="deny")
    await add_grant(db, expired_allow, "demo/*", expires_at=past)
    await add_grant(db, expired_deny, REVENUE, effect="deny", expires_at=past)

    out = await requests_for(db).options(await policy_of(db, sara), REVENUE)

    assert [g.name for g in out.groups] == ["expired-deny"]
    assert out.can_request_resource is False  # sara already reaches it via "mine"


async def test_options_shows_manager_display_names_not_emails(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    lead = await make_user(db, "lead@yougotagift.com")
    lead.display_name = "Lina Lead"
    db.add(lead)
    await db.commit()
    plain = await make_user(db, "plain@yougotagift.com")
    finance = await make_group(db, "finance")
    await add_member(db, finance, lead, "manager")
    await add_member(db, finance, plain)
    await add_grant(db, finance, "demo/*")

    out = await requests_for(db).options(await policy_of(db, sara), REVENUE)

    assert [g.managers for g in out.groups] == [["Lina Lead"]]
    assert "lead@yougotagift.com" not in out.model_dump_json()


async def test_options_is_tenant_scoped(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    other = Group(name="elsewhere", tenant="other")
    db.add(other)
    await db.commit()
    await add_grant(db, other, "demo/*")

    out = await requests_for(db).options(await policy_of(db, sara), REVENUE)

    assert out.groups == []


async def test_options_rejects_a_pattern(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")

    with pytest.raises(InvalidChangeError):
        await requests_for(db).options(await policy_of(db, sara), "demo/*")


def _group(name: str, parent: UUID | None = None) -> GroupFacts:
    return GroupFacts(uuid4(), name, parent, "ygg")


def _grant(
    subject: GroupFacts,
    target: str,
    effect: str = "allow",
    *,
    kind: str = "resource",
    expires_at: datetime | None = None,
) -> GrantFacts:
    return GrantFacts(uuid4(), "group", subject.id, effect, kind, target, expires_at)


def test_groups_granting_is_pure() -> None:
    root = _group("root")
    child = _group("child", root.id)
    deny_child = _group("deny-child", root.id)
    broken = _group("broken")
    clearance_only = _group("clearance-only")
    expired = _group("expired")
    bad_allow = _group("bad-allow")
    groups = {
        g.id: g
        for g in (root, child, deny_child, broken, clearance_only, expired, bad_allow)
    }
    later = NOW + timedelta(days=1)
    grants = [
        _grant(root, "demo/*", expires_at=later),
        _grant(deny_child, REVENUE, "deny"),
        _grant(broken, "demo/*"),
        _grant(broken, "chat:use", kind="capability"),  # malformed: deny-all
        _grant(clearance_only, "pii", kind="clearance"),
        _grant(expired, "demo/*", expires_at=NOW),
        _grant(bad_allow, "demo order"),
    ]

    granting = groups_granting(REVENUE, groups, grants, NOW)

    assert set(granting) == {root.id, child.id}
    # An entity path: the item-level deny on deny-child does not cover it.
    assert set(groups_granting("demo/order", groups, grants, NOW)) == {
        root.id,
        child.id,
        deny_child.id,
    }
    assert groups_granting("other/x/y", groups, grants, NOW) == []


# ---- decidable scope ----------------------------------------------------------


def _policy(
    capabilities: frozenset[str] = frozenset(),
    managed: frozenset[UUID] = frozenset(),
    *,
    active: bool = True,
) -> Policy:
    return Policy(
        user_id=uuid4(),
        tenant="ygg",
        role="viewer",
        active=active,
        policy_version=1,
        capabilities=capabilities,
        managed_group_ids=managed,
    )


def test_decidable_scope_by_capability() -> None:
    parent, child, other = uuid4(), uuid4(), uuid4()
    someone = uuid4()
    both = _policy(frozenset({"admin:users", "admin:groups"}))
    users = _policy(frozenset({"admin:users"}))
    groups = _policy(frozenset({"admin:groups"}))
    manager = _policy(managed=frozenset({parent, child}))
    viewer = _policy()
    inactive = _policy(frozenset({"admin:users", "admin:groups"}), active=False)

    cases = [
        (both, "role", "analyst", True),
        (both, "resource", REVENUE, True),
        (both, "group", str(other), True),
        (users, "role", "analyst", True),
        (users, "resource", REVENUE, True),
        (users, "group", str(other), False),
        (groups, "group", str(other), True),
        (groups, "role", "analyst", False),
        (groups, "resource", REVENUE, False),
        (manager, "group", str(child), True),
        (manager, "group", str(parent), True),
        (manager, "group", str(other), False),
        (manager, "group", "not-a-uuid", False),
        (manager, "role", "analyst", False),
        (viewer, "group", str(other), False),
        (inactive, "role", "analyst", False),
    ]
    for policy, kind, target, expected in cases:
        assert decidable_scope(policy).covers(kind, target, someone) is expected, (
            kind,
            target,
        )
    assert decidable_scope(viewer).empty
    assert decidable_scope(inactive).empty
    assert not decidable_scope(manager).empty
    assert not decidable_scope(both).covers("role", "analyst", both.user_id)


async def test_requests_never_leak_another_tenant(db) -> None:
    """A request row in another tenant is invisible to cancel and to the list."""
    sara = await make_user(db, "sara@yougotagift.com")
    row = AccessRequest(
        tenant="other", user_id=sara.id, kind="resource", target=REVENUE, note="x"
    )
    db.add(row)
    await db.commit()

    assert await requests_for(db).list_own(await policy_of(db, sara)) == []
    with pytest.raises(NotFoundError):
        await requests_for(db).cancel(await policy_of(db, sara), row.id)

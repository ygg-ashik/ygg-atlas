"""Deciding access requests: one transaction per approval, scoped deciders."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlmodel import col, select

from app.access.admin import Actor
from app.access.catalog import CLEARANCE_PEOPLE_NAMES
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.models import AccessRequest, Grant, GroupMember, RbacChange
from app.access.policy import decidable_scope
from app.access.repositories import AccessRepository
from app.access.schemas import AccessRequestCreate, AccessRequestOut, RequestDecision
from app.identity.models import User
from tests.access_helpers import (
    actor_with,
    add_grant,
    add_member,
    bump,
    fresh,
    make_group,
    make_user,
    policy_of,
    policy_version,
    requests_for,
)

REVENUE = "demo/order/revenue"


def _decision(**fields: Any) -> RequestDecision:
    return RequestDecision.model_validate(fields)


async def _ask(db, user: User, kind: str, target: str) -> AccessRequestOut:
    payload = AccessRequestCreate.model_validate(
        {"kind": kind, "target": target, "note": "for the Q4 review"}
    )
    return await requests_for(db).create(await policy_of(db, user), payload)


async def _actions(db) -> list[str]:
    stmt = select(RbacChange).order_by(col(RbacChange.at))
    return [c.action for c in (await db.execute(stmt)).scalars().all()]


async def _status(db, request_id: UUID) -> str:
    row = await db.get(AccessRequest, request_id, populate_existing=True)
    assert row is not None
    return row.status


async def _holding(db, role: str, *capabilities: str) -> Actor:
    """An API actor with `role` plus direct capability grants."""
    user = await make_user(db, f"{role}-{uuid4().hex[:8]}@yougotagift.com", role=role)
    for capability in capabilities:
        await add_grant(db, user, capability, kind="capability")
    return Actor.from_policy(await policy_of(db, user))


# ---- group requests -----------------------------------------------------------


async def test_manager_approves_group_request(db) -> None:
    growth = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    lead = await actor_with(db, "viewer", member_of=growth, standing="manager")
    request = await _ask(db, sara, "group", str(growth.id))
    version = await policy_version(db)
    before = await _actions(db)

    out = await requests_for(db).approve(
        await fresh(db, lead), request.id, _decision(note="welcome")
    )

    assert out.status == "approved"
    assert out.decision_note == "welcome"
    assert out.decided_by is not None
    assert out.decided_by.user_id == lead.user_id
    assert out.decided_at is not None
    assert out.requester is not None
    assert out.requester.email == "sara@yougotagift.com"
    member = await db.get(GroupMember, (growth.id, sara.id), populate_existing=True)
    assert member is not None
    assert member.standing == "member"
    assert (await _actions(db))[len(before) :] == ["member.put", "request.approve"]
    assert await policy_version(db) == version + 1
    row = (
        await db.execute(
            select(RbacChange).where(col(RbacChange.action) == "request.approve")
        )
    ).scalar_one()
    assert row.object_type == "access_request"
    assert row.object_id == str(request.id)
    assert row.before == {"status": "pending"}
    assert row.after == {
        "status": "approved",
        "kind": "group",
        "target": str(growth.id),
        "user_id": str(sara.id),
    }


async def test_manager_of_parent_approves_subgroup_request(db) -> None:
    finance = await make_group(db, "finance")
    payments = await make_group(db, "payments", parent=finance)
    sara = await make_user(db, "sara@yougotagift.com")
    lead = await actor_with(db, "viewer", member_of=finance, standing="manager")
    request = await _ask(db, sara, "group", str(payments.id))

    out = await requests_for(db).approve(await fresh(db, lead), request.id, _decision())

    assert out.status == "approved"
    assert out.target_label == "payments"


async def test_manager_cannot_see_or_decide_role_or_resource_requests(db) -> None:
    growth = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    lead = await actor_with(db, "viewer", member_of=growth, standing="manager")
    role = await _ask(db, sara, "role", "analyst")
    resource = await _ask(db, sara, "resource", REVENUE)
    service = requests_for(db)
    lead = await fresh(db, lead)

    for request in (role, resource):
        with pytest.raises(NotFoundError, match="No such request"):
            await service.approve(lead, request.id, _decision())
        with pytest.raises(NotFoundError, match="No such request"):
            await service.decline(lead, request.id, _decision())
        assert await _status(db, request.id) == "pending"
    page = await service.list_decidable(lead, "pending", None, 50)
    assert page.items == []


async def test_manager_cannot_decide_other_subtree_group_request(db) -> None:
    growth = await make_group(db, "growth")
    finance = await make_group(db, "finance")
    sara = await make_user(db, "sara@yougotagift.com")
    lead = await actor_with(db, "viewer", member_of=growth, standing="manager")
    request = await _ask(db, sara, "group", str(finance.id))

    with pytest.raises(NotFoundError):
        await requests_for(db).approve(await fresh(db, lead), request.id, _decision())
    assert await _status(db, request.id) == "pending"


async def test_admin_users_only_does_not_list_group_requests(db) -> None:
    growth = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    group = await _ask(db, sara, "group", str(growth.id))
    role = await _ask(db, sara, "role", "analyst")
    actor = await _holding(db, "analyst", "admin:users")
    service = requests_for(db)

    page = await service.list_decidable(actor, "pending", None, 50)

    assert [r.id for r in page.items] == [role.id]
    with pytest.raises(NotFoundError):
        await service.approve(actor, group.id, _decision())


async def test_group_approval_when_already_a_manager_is_a_noop_approve(db) -> None:
    growth = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    request = await _ask(db, sara, "group", str(growth.id))
    await add_member(db, growth, sara, "manager")
    admin = await actor_with(db, "admin")
    version = await policy_version(db)
    before = await _actions(db)

    out = await requests_for(db).approve(admin, request.id, _decision())

    assert out.status == "approved"
    member = await db.get(GroupMember, (growth.id, sara.id), populate_existing=True)
    assert member is not None
    assert member.standing == "manager"
    assert (await _actions(db))[len(before) :] == ["request.approve"]
    assert await policy_version(db) == version + 1


# ---- role requests ------------------------------------------------------------


async def test_admin_approves_a_role_request(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    request = await _ask(db, sara, "role", "analyst")
    admin = await actor_with(db, "admin")
    before = await _actions(db)

    out = await requests_for(db).approve(admin, request.id, _decision())

    assert out.status == "approved"
    user = await db.get(User, sara.id, populate_existing=True)
    assert user is not None
    assert user.role == "analyst"
    assert (await _actions(db))[len(before) :] == ["user.role", "request.approve"]


async def test_role_approval_runs_d10(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    to_admin = await _ask(db, sara, "role", "admin")
    omar = await make_user(db, "omar@yougotagift.com", role="analyst")
    await add_grant(db, omar, "admin:tokens", kind="capability")
    to_builder = await _ask(db, omar, "role", "builder")
    approver = await _holding(db, "builder", "admin:users")
    service = requests_for(db)

    with pytest.raises(AccessDeniedError, match="more access than your own"):
        await service.approve(approver, to_admin.id, _decision())
    with pytest.raises(AccessDeniedError, match="more access than your own"):
        await service.approve(approver, to_builder.id, _decision())
    assert await _status(db, to_admin.id) == "pending"
    assert await _status(db, to_builder.id) == "pending"


async def test_role_approval_never_demotes(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    request = await _ask(db, sara, "role", "analyst")
    await make_user(db, "sara@yougotagift.com", role="builder")
    admin = await actor_with(db, "admin")
    before = await _actions(db)

    out = await requests_for(db).approve(admin, request.id, _decision())

    assert out.status == "approved"
    user = await db.get(User, sara.id, populate_existing=True)
    assert user is not None
    assert user.role == "builder"
    assert (await _actions(db))[len(before) :] == ["request.approve"]


# ---- resource requests --------------------------------------------------------


async def _user_grants(db, user_id: UUID) -> list[Grant]:
    stmt = select(Grant).where(
        col(Grant.subject_type) == "user", col(Grant.subject_id) == user_id
    )
    return list((await db.execute(stmt)).scalars().all())


async def test_resource_approval_creates_exact_user_grant(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    sara_id = sara.id
    request = await _ask(db, sara, "resource", REVENUE)
    admin = await actor_with(db, "admin")
    before = await _actions(db)

    out = await requests_for(db).approve(admin, request.id, _decision(note="ok"))

    assert out.status == "approved"
    [grant] = await _user_grants(db, sara_id)
    assert grant.target == REVENUE
    assert grant.target_kind == "resource"
    assert grant.effect == "allow"
    assert grant.reason == f"Access request {request.id}: for the Q4 review"
    assert grant.expires_at is not None
    expected = datetime.now(UTC) + timedelta(days=90)
    expires = grant.expires_at.replace(tzinfo=UTC)
    assert abs(expires - expected) < timedelta(minutes=1)
    assert (await _actions(db))[len(before) :] == ["grant.create", "request.approve"]
    change = (
        await db.execute(
            select(RbacChange).where(col(RbacChange.action) == "request.approve")
        )
    ).scalar_one()
    assert change.after is not None
    assert "expires_at" in change.after
    assert (await policy_of(db, sara)).allows(REVENUE)


async def test_resource_approval_expiry_explicit_null_and_value(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    sara_id = sara.id
    forever = await _ask(db, sara, "resource", REVENUE)
    later = await _ask(db, sara, "resource", "demo/order/count")
    past = await _ask(db, sara, "resource", "demo/order/aov")
    admin = await actor_with(db, "admin")
    service = requests_for(db)
    when = datetime.now(UTC) + timedelta(days=7)

    await service.approve(admin, forever.id, _decision(expires_at=None))
    await service.approve(
        await fresh(db, admin), later.id, _decision(expires_at=when.isoformat())
    )
    with pytest.raises(InvalidChangeError, match="future"):
        await service.approve(
            await fresh(db, admin),
            past.id,
            _decision(expires_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat()),
        )

    grants = {g.target: g for g in await _user_grants(db, sara_id)}
    assert grants[REVENUE].expires_at is None
    count_expiry = grants["demo/order/count"].expires_at
    assert count_expiry is not None
    assert abs(count_expiry.replace(tzinfo=UTC) - when) < timedelta(seconds=1)
    assert "demo/order/aov" not in grants
    assert await _status(db, past.id) == "pending"


async def test_expires_at_on_group_or_role_request_is_422(db) -> None:
    growth = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    group = await _ask(db, sara, "group", str(growth.id))
    role = await _ask(db, sara, "role", "analyst")
    admin = await actor_with(db, "admin")
    service = requests_for(db)

    for request in (group, role):
        with pytest.raises(InvalidChangeError, match="resource"):
            await service.approve(admin, request.id, _decision(expires_at=None))
        with pytest.raises(InvalidChangeError):
            await service.decline(admin, request.id, _decision(expires_at=None))
        assert await _status(db, request.id) == "pending"


async def test_resource_approval_with_existing_live_grant_is_noop_approve(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    sara_id = sara.id
    request = await _ask(db, sara, "resource", REVENUE)
    await add_grant(db, sara, REVENUE)
    admin = await actor_with(db, "admin")
    before = await _actions(db)

    out = await requests_for(db).approve(admin, request.id, _decision())

    assert out.status == "approved"
    assert len(await _user_grants(db, sara_id)) == 1
    assert (await _actions(db))[len(before) :] == ["request.approve"]


# ---- the decision itself ------------------------------------------------------


async def test_nobody_decides_their_own_request(db) -> None:
    admin = await actor_with(db, "admin")
    me = await db.get(User, admin.user_id)
    assert me is not None
    request = await _ask(db, me, "resource", REVENUE)
    service = requests_for(db)

    with pytest.raises(ConflictError, match="You can't decide your own request"):
        await service.approve(await fresh(db, admin), request.id, _decision())
    with pytest.raises(ConflictError, match="You can't decide your own request"):
        await service.decline(await fresh(db, admin), request.id, _decision())
    assert await _status(db, request.id) == "pending"


async def test_stale_actor_gets_409_and_request_stays_pending(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    sara_id = sara.id
    request = await _ask(db, sara, "resource", REVENUE)
    admin = await actor_with(db, "admin")
    await bump(db)

    with pytest.raises(ConflictError, match="Access changed"):
        await requests_for(db).approve(admin, request.id, _decision())
    assert await _status(db, request.id) == "pending"
    assert await _user_grants(db, sara_id) == []


async def test_already_decided_request_is_409(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    declined = await _ask(db, sara, "resource", REVENUE)
    cancelled = await _ask(db, sara, "resource", "demo/order/count")
    approved = await _ask(db, sara, "resource", "demo/order/aov")
    service = requests_for(db)
    await service.decline(Actor.cli(), declined.id, _decision())
    await service.cancel(await policy_of(db, sara), cancelled.id)
    await service.approve(Actor.cli(), approved.id, _decision())
    admin = await actor_with(db, "admin")

    for request in (declined, cancelled, approved):
        with pytest.raises(ConflictError, match="already decided"):
            await service.approve(await fresh(db, admin), request.id, _decision())
        with pytest.raises(ConflictError, match="already decided"):
            await service.decline(await fresh(db, admin), request.id, _decision())


async def test_decline_takes_the_lock_but_does_not_bump(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    request = await _ask(db, sara, "resource", REVENUE)
    admin = await actor_with(db, "admin")
    await bump(db)
    service = requests_for(db)

    with pytest.raises(ConflictError, match="Access changed"):
        await service.decline(admin, request.id, _decision())
    assert await _status(db, request.id) == "pending"

    version = await policy_version(db)
    out = await service.decline(await fresh(db, admin), request.id, _decision())
    assert out.status == "declined"
    assert await policy_version(db) == version


async def test_decline_rechecks_authority(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    request = await _ask(db, sara, "role", "analyst")
    viewer = await actor_with(db, "viewer")

    with pytest.raises(NotFoundError):
        await requests_for(db).decline(viewer, request.id, _decision())
    assert await _status(db, request.id) == "pending"


async def test_cross_tenant_request_is_404(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    row = AccessRequest(
        tenant="other", user_id=sara.id, kind="role", target="analyst", note="x"
    )
    db.add(row)
    await db.commit()
    admin = await actor_with(db, "admin")
    service = requests_for(db)

    for decide in (service.approve, service.decline):
        with pytest.raises(NotFoundError, match="No such request"):
            await decide(await fresh(db, admin), row.id, _decision())
        with pytest.raises(NotFoundError, match="No such request"):
            await decide(await fresh(db, admin), uuid4(), _decision())
    assert await _status(db, row.id) == "pending"


# ---- the queue ----------------------------------------------------------------


async def test_list_is_keyset_paged_and_filtered_by_status(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    made = [await _ask(db, sara, "resource", f"demo/order/m{i}") for i in range(5)]
    elsewhere = await make_user(db, "x@other.example")
    db.add(
        AccessRequest(
            tenant="other", user_id=elsewhere.id, kind="role", target="admin", note="x"
        )
    )
    await db.commit()
    service = requests_for(db)
    await service.decline(Actor.cli(), made[0].id, _decision())
    admin = await actor_with(db, "admin")

    seen: list[UUID] = []
    cursor: str | None = None
    pages = 0
    for _ in range(5):
        page = await service.list_decidable(admin, "pending", cursor, 2)
        pages += 1
        seen.extend(r.id for r in page.items)
        assert all(r.requester is not None for r in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert pages == 2
    assert seen == [r.id for r in reversed(made[1:])]

    declined = await service.list_decidable(admin, "declined", None, 50)
    assert [r.id for r in declined.items] == [made[0].id]
    everything = await service.list_decidable(admin, None, None, 50)
    assert len(everything.items) == 5


async def test_list_pages_through_identical_timestamps(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    moment = datetime(2026, 10, 1, 9, tzinfo=UTC)
    rows = [
        AccessRequest(
            user_id=sara.id,
            kind="resource",
            target=f"demo/order/t{i}",
            note="x",
            created_at=moment,
        )
        for i in range(5)
    ]
    db.add_all(rows)
    await db.commit()
    admin = await actor_with(db, "admin")
    service = requests_for(db)

    seen: list[UUID] = []
    cursor: str | None = None
    for _ in range(5):
        page = await service.list_decidable(admin, "pending", cursor, 2)
        seen.extend(r.id for r in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert sorted(seen) == sorted(r.id for r in rows)
    assert len(seen) == len(set(seen))


async def test_tampered_cursor_is_422(db) -> None:
    admin = await actor_with(db, "admin")

    with pytest.raises(InvalidChangeError, match="page link is invalid"):
        await requests_for(db).list_decidable(admin, "pending", "!!not-a-cursor", 50)


async def test_an_empty_scope_cannot_list(db) -> None:
    viewer = await actor_with(db, "viewer")

    with pytest.raises(AccessDeniedError, match="group manager"):
        await requests_for(db).list_decidable(viewer, "pending", None, 50)


async def test_count_decidable_matches_the_list(db) -> None:
    growth = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    await _ask(db, sara, "group", str(growth.id))
    await _ask(db, sara, "role", "analyst")
    lead = await actor_with(db, "viewer", member_of=growth, standing="manager")
    admin = await actor_with(db, "admin")
    repo = AccessRepository(db)

    lead = await fresh(db, lead)
    assert lead.policy is not None
    assert admin.policy is not None
    assert await repo.requests.count_decidable("ygg", decidable_scope(lead.policy)) == 1
    assert (
        await repo.requests.count_decidable("ygg", decidable_scope(admin.policy)) == 2
    )


async def test_approving_for_a_disabled_requester_is_409(db) -> None:
    growth = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    sara_id, growth_id = sara.id, growth.id  # rollbacks expire loaded rows
    requests = [
        await _ask(db, sara, "group", str(growth_id)),
        await _ask(db, sara, "role", "analyst"),
        await _ask(db, sara, "resource", REVENUE),
    ]
    await make_user(db, "sara@yougotagift.com", status="disabled")
    admin = await actor_with(db, "admin")
    service = requests_for(db)
    before = await _actions(db)

    for request in requests:
        with pytest.raises(ConflictError, match="requester's account is disabled"):
            await service.approve(await fresh(db, admin), request.id, _decision())
        assert await _status(db, request.id) == "pending"
    assert await _actions(db) == before
    assert await _user_grants(db, sara_id) == []
    member = await db.get(GroupMember, (growth_id, sara_id), populate_existing=True)
    assert member is None


# ---- phase 3 rules hold on the approval path ------------------------------


async def test_approving_into_a_cleared_group_needs_the_clearance(db) -> None:
    # C10: joining inherits the lineage's clearance allows, so the approval
    # path (_stage_member) refuses an uncleared decider, as put_member does.
    growth = await make_group(db, "growth")
    await add_grant(db, growth, CLEARANCE_PEOPLE_NAMES, kind="clearance")
    sara = await make_user(db, "sara@yougotagift.com")
    # Not a member: a manager of the group would already inherit the clearance.
    groups_admin = await _holding(db, "viewer", "admin:groups")
    request = await _ask(db, sara, "group", str(growth.id))
    version = await policy_version(db)
    sara_id = sara.id  # read before the refused write rolls the session back

    with pytest.raises(AccessDeniedError, match="clearance"):
        await requests_for(db).approve(groups_admin, request.id, _decision())

    assert await _status(db, request.id) == "pending"
    joined = select(GroupMember).where(col(GroupMember.user_id) == sara_id)
    assert (await db.execute(joined)).first() is None
    assert await policy_version(db) == version


async def test_an_approved_resource_grant_is_unscoped(db) -> None:
    # The approval path builds its grant in _stage_grant with no row scope:
    # a scoped grant only ever comes from the grant editor.
    sara = await make_user(db, "sara@yougotagift.com")
    admin = await _holding(db, "viewer", "admin:users")
    request = await _ask(db, sara, "resource", REVENUE)

    await requests_for(db).approve(admin, request.id, _decision())

    grant = (
        await db.execute(select(Grant).where(col(Grant.subject_id) == sara.id))
    ).scalar_one()
    assert grant.target == REVENUE
    assert grant.row_scope is None

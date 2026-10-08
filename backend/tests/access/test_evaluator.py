"""The evaluator, case by case (spec §5.4, §13). Pure: no database."""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.access.catalog import ADMIN_GROUPS, CHAT_USE, MCP_USE
from app.access.evaluator import evaluate
from app.access.facts import GrantFacts, GroupFacts, PolicyInputs, UserFacts
from app.access.policy import Policy

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
USER = uuid4()
ROOT, CHILD, OTHER_TENANT = uuid4(), uuid4(), uuid4()
GROUPS = {
    ROOT: GroupFacts(ROOT, "marketing", None, "ygg"),
    CHILD: GroupFacts(CHILD, "growth", ROOT, "ygg"),
    OTHER_TENANT: GroupFacts(OTHER_TENANT, "acme", None, "acme"),
}
REVENUE = "demo/order/revenue"


def grant(
    subject: UUID,
    target: str = "*",
    *,
    effect: str = "allow",
    kind: str = "resource",
    expires_at: datetime | None = None,
) -> GrantFacts:
    subject_type = "user" if subject == USER else "group"
    return GrantFacts(uuid4(), subject_type, subject, effect, kind, target, expires_at)


def policy(
    *,
    role: str = "viewer",
    status: str = "active",
    member_of: dict[UUID, str] | None = None,
    grants: Iterable[GrantFacts] = (),
    groups: dict[UUID, GroupFacts] | None = None,
) -> Policy:
    inputs = PolicyInputs(
        user=UserFacts(USER, role, status, "ygg"),
        groups=GROUPS if groups is None else groups,
        memberships=member_of or {},
        grants=list(grants),
        policy_version=7,
    )
    return evaluate(inputs, NOW)


def test_new_user_can_chat_but_sees_no_data() -> None:
    p = policy()
    assert p.has(CHAT_USE)
    assert not p.allows(REVENUE)
    assert not p.has_data_access
    assert p.policy_version == 7


def test_group_grant_applies_to_members_only() -> None:
    g = grant(ROOT, "demo/*")
    assert policy(member_of={ROOT: "member"}, grants=[g]).allows(REVENUE)
    assert not policy(grants=[g]).allows(REVENUE)


def test_subgroup_members_inherit_parent_grants() -> None:
    assert policy(member_of={CHILD: "member"}, grants=[grant(ROOT)]).allows(REVENUE)


def test_parent_members_do_not_inherit_subgroup_grants() -> None:
    assert not policy(member_of={ROOT: "member"}, grants=[grant(CHILD)]).allows(REVENUE)


def test_deny_wins_at_every_level() -> None:
    allow_child = grant(CHILD, "demo/*")
    deny_parent = grant(ROOT, "demo/order/*", effect="deny")
    p = policy(member_of={CHILD: "member"}, grants=[allow_child, deny_parent])
    assert not p.allows(REVENUE)
    assert p.allows("demo/checkout/checkout_funnel")


def test_direct_user_allow_cannot_beat_a_group_deny() -> None:
    p = policy(
        member_of={ROOT: "member"},
        grants=[grant(USER, REVENUE), grant(ROOT, "demo/*", effect="deny")],
    )
    assert not p.allows(REVENUE)


def test_direct_user_grant_works_without_groups() -> None:
    p = policy(grants=[grant(USER, REVENUE)])
    decision = p.decide(REVENUE)
    assert decision.allowed
    assert decision.rule is not None
    assert decision.rule.origin == "user"


def test_decision_names_the_deciding_grant_and_group() -> None:
    deny = grant(ROOT, "demo/*", effect="deny")
    p = policy(member_of={ROOT: "member"}, grants=[grant(ROOT), deny])
    assert p.deny_reason(REVENUE) == f"denied by grant {deny.id} (group:marketing)"
    assert policy().deny_reason(REVENUE) == "no grant allows it"


def test_expired_grants_are_ignored() -> None:
    past = grant(USER, expires_at=NOW - timedelta(minutes=1))
    assert not policy(grants=[past]).allows(REVENUE)


def test_future_expiry_is_kept_and_bounds_the_cache() -> None:
    soon = NOW + timedelta(hours=1)
    later = NOW + timedelta(days=1)
    p = policy(grants=[grant(USER, expires_at=later), grant(USER, expires_at=soon)])
    assert p.allows(REVENUE)
    assert p.valid_until == soon


def test_user_capability_overrides() -> None:
    p = policy(
        grants=[
            grant(USER, MCP_USE, kind="capability"),
            grant(USER, CHAT_USE, kind="capability", effect="deny"),
        ]
    )
    assert p.has(MCP_USE)
    assert not p.has(CHAT_USE)


def test_groups_never_grant_capabilities() -> None:
    p = policy(
        member_of={ROOT: "member"}, grants=[grant(ROOT, MCP_USE, kind="capability")]
    )
    assert not p.has(MCP_USE)


def test_unknown_capability_grant_is_ignored() -> None:
    p = policy(grants=[grant(USER, "root:everything", kind="capability")])
    assert p.capabilities == {CHAT_USE}


def test_clearance_grants_are_ignored_until_phase_3() -> None:
    p = policy(grants=[grant(USER, "fields:people_names", kind="clearance")])
    assert not p.has_data_access


def test_other_tenants_groups_grant_nothing() -> None:
    p = policy(member_of={OTHER_TENANT: "member"}, grants=[grant(OTHER_TENANT)])
    assert not p.allows(REVENUE)


def test_disabled_user_gets_nothing() -> None:
    p = policy(status="disabled", grants=[grant(USER)])
    assert not p.active
    assert not p.has(CHAT_USE)
    assert not p.allows(REVENUE)


def test_unknown_role_gets_no_capabilities() -> None:
    assert policy(role="superuser").capabilities == frozenset()


def test_unknown_effect_grants_nothing() -> None:
    assert not policy(grants=[grant(USER, effect="maybe")]).allows(REVENUE)


def test_a_group_cycle_cannot_hang_the_evaluator() -> None:
    a, b = uuid4(), uuid4()
    cyclic = {a: GroupFacts(a, "a", b, "ygg"), b: GroupFacts(b, "b", a, "ygg")}
    p = policy(member_of={a: "member"}, grants=[grant(b)], groups=cyclic)
    assert p.allows(REVENUE)


def test_managers_manage_their_group_and_its_subgroups() -> None:
    manager = policy(member_of={ROOT: "manager"})
    assert manager.can_manage_members(ROOT)
    assert manager.can_manage_members(CHILD)
    member = policy(member_of={ROOT: "member"})
    assert not member.can_manage_members(ROOT)


def test_admin_groups_capability_manages_any_group() -> None:
    admin = policy(role="admin")
    assert admin.has(ADMIN_GROUPS)
    assert admin.can_manage_members(CHILD)
    assert not admin.allows(REVENUE)  # decision D2: no data bypass for admins


# --- code review follow-ups -------------------------------------------------


def test_invalid_stored_deny_pattern_denies_everything() -> None:
    bad_deny = grant(USER, "demo/order", effect="deny")  # 2-segment literal: invalid
    allow_all = grant(USER, "*")
    p = policy(grants=[allow_all, bad_deny])
    assert not p.allows(REVENUE)
    assert p.deny_reason(REVENUE) == f"denied by grant {bad_deny.id} (user)"


def test_invalid_stored_allow_pattern_grants_nothing() -> None:
    bad_allow = grant(USER, "Demo/*")  # uppercase segment: invalid
    p = policy(grants=[bad_allow])
    assert not p.allows(REVENUE)
    assert not p.has_data_access


def test_user_resource_deny_beats_group_allow() -> None:
    p = policy(
        member_of={ROOT: "member"},
        grants=[grant(ROOT, "demo/*"), grant(USER, REVENUE, effect="deny")],
    )
    assert not p.allows(REVENUE)


def test_membership_in_unknown_group_grants_nothing() -> None:
    unknown = uuid4()
    p = policy(member_of={unknown: "manager"}, grants=[grant(unknown)])
    assert not p.allows(REVENUE)
    assert not p.can_manage_members(unknown)
    assert p.group_ids == frozenset()


def test_grant_on_other_tenant_parent_does_not_reach_child() -> None:
    child_of_foreign_parent = GroupFacts(uuid4(), "sub", OTHER_TENANT, "ygg")
    groups = {**GROUPS, child_of_foreign_parent.id: child_of_foreign_parent}
    p = policy(
        member_of={child_of_foreign_parent.id: "member"},
        grants=[grant(OTHER_TENANT)],
        groups=groups,
    )
    assert not p.allows(REVENUE)


def test_expiring_deny_bounds_valid_until_then_expires() -> None:
    soon = NOW + timedelta(minutes=5)
    inputs = PolicyInputs(
        user=UserFacts(USER, "viewer", "active", "ygg"),
        groups=GROUPS,
        memberships={},
        grants=[
            grant(USER, "demo/*"),
            grant(USER, "demo/*", effect="deny", expires_at=soon),
        ],
        policy_version=7,
    )
    before = evaluate(inputs, NOW)
    assert not before.allows(REVENUE)
    assert before.valid_until == soon
    after = evaluate(inputs, soon + timedelta(seconds=1))
    assert after.allows(REVENUE)


def test_expiry_at_exact_now_is_expired() -> None:
    p = policy(grants=[grant(USER, expires_at=NOW)])
    assert not p.allows(REVENUE)


def test_user_capability_deny_wins_over_allow() -> None:
    p = policy(
        grants=[
            grant(USER, MCP_USE, kind="capability", effect="deny"),
            grant(USER, MCP_USE, kind="capability"),
        ]
    )
    assert not p.has(MCP_USE)


def test_admin_capability_deny_removes_manage_rights() -> None:
    p = policy(
        role="admin",
        grants=[grant(USER, ADMIN_GROUPS, kind="capability", effect="deny")],
    )
    assert not p.has(ADMIN_GROUPS)
    assert not p.can_manage_members(CHILD)


def test_evaluation_is_deterministic_regardless_of_grant_order() -> None:
    grants = [grant(USER, "demo/*"), grant(USER, "demo/order/*", effect="deny")]
    inputs = PolicyInputs(
        user=UserFacts(USER, "viewer", "active", "ygg"),
        groups=GROUPS,
        memberships={},
        grants=grants,
        policy_version=7,
    )
    reversed_inputs = PolicyInputs(
        user=UserFacts(USER, "viewer", "active", "ygg"),
        groups=GROUPS,
        memberships={},
        grants=list(reversed(grants)),
        policy_version=7,
    )
    assert evaluate(inputs, NOW) == evaluate(reversed_inputs, NOW)


def test_manager_over_a_cycle_terminates() -> None:
    a, b = uuid4(), uuid4()
    cyclic = {a: GroupFacts(a, "a", b, "ygg"), b: GroupFacts(b, "b", a, "ygg")}
    p = policy(member_of={a: "manager"}, groups=cyclic)
    assert p.can_manage_members(a)
    assert p.can_manage_members(b)


def test_manager_standing_in_other_tenant_group_manages_nothing() -> None:
    p = policy(member_of={OTHER_TENANT: "manager"})
    assert not p.can_manage_members(OTHER_TENANT)


def test_unknown_status_gives_deny_all() -> None:
    p = policy(status="pending")
    assert not p.active
    assert not p.has(CHAT_USE)
    assert not p.allows(REVENUE)


def test_evaluate_rejects_naive_datetime() -> None:
    inputs = PolicyInputs(
        user=UserFacts(USER, "viewer", "active", "ygg"),
        groups=GROUPS,
        memberships={},
        grants=[],
        policy_version=7,
    )
    naive = datetime(2026, 10, 9, 12, 0)  # noqa: DTZ001  # deliberately naive
    with pytest.raises(ValueError, match="aware datetime"):
        evaluate(inputs, naive)


def test_more_specific_allow_rule_is_reported() -> None:
    p = policy(grants=[grant(USER, "*"), grant(USER, "demo/order/*")])
    decision = p.decide(REVENUE)
    assert decision.rule is not None
    assert decision.rule.pattern == "demo/order/*"

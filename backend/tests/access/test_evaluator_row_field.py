"""Row scopes, clearances and label modes in the evaluator (phase 3, D3.3, D3.4, D3.9).

Pure: no database. Local helpers on purpose (no imports from other test modules).
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from structlog.testing import capture_logs

from app.access.catalog import CLEARANCE_BUSINESS_NAMES, CLEARANCE_PEOPLE_NAMES
from app.access.evaluator import evaluate
from app.access.facts import GrantFacts, GroupFacts, PolicyInputs, UserFacts
from app.access.policy import LabelMode, Policy

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
USER = uuid4()
TEAM = uuid4()
GROUPS = {TEAM: GroupFacts(TEAM, "csm", None, "ygg")}
REVENUE = "demo/order/revenue"
TASKS = "deepsales/ds_task/open_tasks"


def grant(
    target: str = "*",
    *,
    scope: object = None,
    effect: str = "allow",
    kind: str = "resource",
    subject: UUID = USER,
) -> GrantFacts:
    subject_type = "user" if subject == USER else "group"
    return GrantFacts(
        uuid4(),
        subject_type,
        subject,
        effect,
        kind,
        target,
        None,
        # Malformed shapes on purpose: the stored column is JSON.
        row_scope=cast("Mapping[str, Sequence[str]] | None", scope),
    )


def policy(
    *grants: GrantFacts,
    attributes: Mapping[str, str] | None = None,
    self_attributes: Mapping[str, str] | None = None,
    label_modes: Mapping[str, tuple[str, int]] | None = None,
    member_of: Iterable[UUID] = (),
    status: str = "active",
) -> Policy:
    inputs = PolicyInputs(
        user=UserFacts(USER, "viewer", status, "ygg"),
        groups=GROUPS,
        memberships=dict.fromkeys(member_of, "member"),
        grants=list(grants),
        policy_version=3,
        attributes=attributes or {},
        self_attributes=self_attributes or {},
        label_modes=label_modes or {},
    )
    return evaluate(inputs, NOW)


def scope_of(p: Policy, resource: str) -> list[dict[str, set[str]]] | None:
    result = p.row_scope(resource)
    if result is None:
        return None
    return [{d: set(v) for d, v in alt.items()} for alt in result]


# --- combining scopes (D3.3) ---------------------------------------------------


def test_an_unscoped_allow_wins() -> None:
    p = policy(grant("demo/*", scope={"channel": ["b2c"]}), grant("demo/order/*"))
    assert p.allows(REVENUE)
    assert p.row_scope(REVENUE) is None


def test_two_scoped_grants_are_ored() -> None:
    p = policy(
        grant("demo/*", scope={"channel": ["b2c"]}),
        grant("demo/order/*", scope={"channel": ["b2b"]}),
    )
    assert sorted(scope_of(p, REVENUE) or [], key=str) == [
        {"channel": {"b2b"}},
        {"channel": {"b2c"}},
    ]


def test_one_grant_ands_its_dimensions() -> None:
    p = policy(grant("demo/*", scope={"channel": ["b2c"], "country": ["AE", "SA"]}))
    assert scope_of(p, REVENUE) == [{"channel": {"b2c"}, "country": {"AE", "SA"}}]


def test_identical_conjunctions_are_deduplicated() -> None:
    p = policy(
        grant("demo/*", scope={"channel": ["b2c"]}),
        grant("demo/order/*", scope={"channel": ["b2c", "b2c"]}, subject=TEAM),
        member_of=[TEAM],
    )
    assert scope_of(p, REVENUE) == [{"channel": {"b2c"}}]


def test_only_matching_allows_contribute() -> None:
    p = policy(
        grant("demo/order/*", scope={"channel": ["b2c"]}),
        grant("deepsales/*", scope={"csm": ["Omar"]}),
    )
    assert scope_of(p, REVENUE) == [{"channel": {"b2c"}}]
    assert scope_of(p, TASKS) == [{"csm": {"Omar"}}]


def test_deny_beats_a_scoped_allow() -> None:
    p = policy(
        grant("demo/*", scope={"channel": ["b2c"]}),
        grant("demo/order/revenue", effect="deny"),
    )
    assert not p.allows(REVENUE)
    assert p.row_scope(REVENUE) == ()


def test_no_allow_and_inactive_policies_have_an_empty_scope() -> None:
    assert policy().row_scope(REVENUE) == ()
    disabled = policy(grant("*"), status="disabled")
    assert disabled.row_scope(REVENUE) == ()


def test_the_scope_rides_on_the_rule_as_sorted_hashable_pairs() -> None:
    p = policy(grant("demo/*", scope={"country": ["SA", "AE"], "channel": ["b2c"]}))
    (rule,) = p.allow_rules
    assert rule.scope == (
        ("channel", frozenset({"b2c"})),
        ("country", frozenset({"AE", "SA"})),
    )
    assert hash(rule)  # usable in sets and as dict keys
    (unscoped,) = policy(grant("demo/*")).allow_rules
    assert unscoped.scope is None


# --- $self (D3.4, C1, U4) ------------------------------------------------------


def test_self_resolves_from_an_attribute() -> None:
    p = policy(
        grant("deepsales/*", scope={"csm": ["$self"]}),
        attributes={"csm_name": "Rania"},
        self_attributes={"csm": "csm_name"},
    )
    assert scope_of(p, TASKS) == [{"csm": {"Rania"}}]
    mixed = policy(
        grant("deepsales/*", scope={"csm": ["$self", "Omar"]}),
        attributes={"csm_name": "Rania"},
        self_attributes={"csm": "csm_name"},
    )
    assert scope_of(mixed, TASKS) == [{"csm": {"Rania", "Omar"}}]


def test_self_resolves_from_the_email_builtin() -> None:
    p = policy(
        grant("deepsales/*", scope={"owner": ["$self"]}),
        attributes={"email": "rania@yougotagift.com", "user_id": str(USER)},
        self_attributes={"owner": "email"},
    )
    assert scope_of(p, TASKS) == [{"owner": {"rania@yougotagift.com"}}]


def test_a_missing_attribute_skips_the_grant() -> None:
    scoped = grant("deepsales/*", scope={"csm": ["$self"]})
    other = grant("demo/*", scope={"channel": ["b2c"]})
    with capture_logs() as logs:
        p = policy(scoped, other, self_attributes={"csm": "csm_name"})
    assert not p.allows(TASKS)
    assert p.row_scope(TASKS) == ()
    assert [r.grant_id for r in p.allow_rules] == [other.id]
    assert not p.deny_rules  # a per-user condition, not deny-all
    assert p.capabilities  # role bundle intact
    (skipped,) = p.skipped
    assert skipped.grant_id == scoped.id
    assert skipped.pattern == "deepsales/*"
    assert skipped.origin == "user"
    assert skipped.reason == "missing attribute 'csm_name'"
    unresolved = [e for e in logs if e["event"] == "access.scope_self_unresolved"]
    assert len(unresolved) == 1
    assert unresolved[0]["grant_id"] == str(scoped.id)
    assert "Rania" not in str(unresolved)


def test_an_empty_attribute_value_counts_as_missing() -> None:
    p = policy(
        grant("deepsales/*", scope={"csm": ["$self"]}),
        attributes={"csm_name": ""},
        self_attributes={"csm": "csm_name"},
    )
    assert not p.allows(TASKS)
    assert p.skipped[0].reason == "missing attribute 'csm_name'"


def test_self_on_a_dimension_without_a_self_attribute_skips() -> None:
    p = policy(
        grant("demo/*", scope={"x": ["$self"]}),
        attributes={"csm_name": "Rania"},
        self_attributes={"csm": "csm_name"},
    )
    assert not p.allows(REVENUE)
    assert p.skipped[0].reason == "dimension 'x' has no $self attribute"


def test_self_resolves_on_a_group_grant() -> None:
    p = policy(
        grant("deepsales/*", scope={"csm": ["$self"]}, subject=TEAM),
        member_of=[TEAM],
        attributes={"csm_name": "Rania"},
        self_attributes={"csm": "csm_name"},
    )
    assert scope_of(p, TASKS) == [{"csm": {"Rania"}}]
    assert p.allow_rules[0].origin == "group:csm"
    assert not p.skipped


def test_a_skipped_group_grant_names_its_group() -> None:
    p = policy(
        grant("deepsales/*", scope={"csm": ["$self"]}, subject=TEAM),
        member_of=[TEAM],
        self_attributes={"csm": "csm_name"},
    )
    assert p.skipped[0].origin == "group:csm"


# --- malformed row scopes (D3.3) -----------------------------------------------

MALFORMED: Sequence[tuple[str, object, str, str]] = [
    ("empty mapping", {}, "allow", "resource"),
    ("empty list", {"csm": []}, "allow", "resource"),
    ("non-string value", {"csm": [1]}, "allow", "resource"),
    ("string instead of list", {"csm": "Omar"}, "allow", "resource"),
    ("empty string value", {"csm": [""]}, "allow", "resource"),
    ("non-dict shape", ["csm"], "allow", "resource"),
    ("bad key", {"Bad": ["x"]}, "allow", "resource"),
    ("non-string key", {1: ["x"]}, "allow", "resource"),
    ("101 values", {"csm": [f"v{i}" for i in range(101)]}, "allow", "resource"),
    ("21 dimensions", {f"d{i}": ["x"] for i in range(21)}, "allow", "resource"),
    ("scope on a deny", {"csm": ["x"]}, "deny", "resource"),
    ("scope on a capability", {"csm": ["x"]}, "allow", "capability"),
    ("scope on a clearance", {"csm": ["x"]}, "allow", "clearance"),
]


@pytest.mark.parametrize(
    ("scope", "effect", "kind"),
    [case[1:] for case in MALFORMED],
    ids=[case[0] for case in MALFORMED],
)
def test_malformed_row_scope_denies_everything(
    scope: object, effect: str, kind: str
) -> None:
    target = "chat:use" if kind == "capability" else "demo/*"
    if kind == "clearance":
        target = CLEARANCE_PEOPLE_NAMES
    bad = grant(target, scope=scope, effect=effect, kind=kind)
    with capture_logs() as logs:
        p = policy(grant("*"), grant(CLEARANCE_BUSINESS_NAMES, kind="clearance"), bad)
    assert not p.allows(REVENUE)
    assert not p.allows(TASKS)
    assert p.row_scope(REVENUE) == ()
    assert p.capabilities == frozenset()
    assert p.clearances == frozenset()
    assert any(e["event"] == "access.malformed_grant" for e in logs)


def test_limits_are_inclusive() -> None:
    p = policy(
        grant("demo/*", scope={f"d{i}": ["x"] for i in range(20)}),
        grant("deepsales/*", scope={"csm": [f"v{i}" for i in range(100)]}),
    )
    assert p.allows(REVENUE)
    assert p.allows(TASKS)


# --- clearances (D3.3: D1 lifted) ----------------------------------------------


def test_clearances_are_allows_minus_denies() -> None:
    p = policy(
        grant(CLEARANCE_PEOPLE_NAMES, kind="clearance", subject=TEAM),
        grant(CLEARANCE_BUSINESS_NAMES, kind="clearance"),
        grant(CLEARANCE_BUSINESS_NAMES, kind="clearance", effect="deny", subject=TEAM),
        grant("fields:secret_sauce", kind="clearance"),
        member_of=[TEAM],
    )
    assert p.clearances == {CLEARANCE_PEOPLE_NAMES}
    assert p.has_clearance(CLEARANCE_PEOPLE_NAMES)
    assert not p.has_clearance(CLEARANCE_BUSINESS_NAMES)
    assert not p.has_clearance("fields:secret_sauce")
    assert not p.has_data_access  # a clearance is not a resource grant


def test_inactive_policy_has_no_clearance() -> None:
    p = policy(grant(CLEARANCE_PEOPLE_NAMES, kind="clearance"), status="disabled")
    assert not p.has_clearance(CLEARANCE_PEOPLE_NAMES)


def test_non_members_get_no_group_clearance() -> None:
    p = policy(grant(CLEARANCE_PEOPLE_NAMES, kind="clearance", subject=TEAM))
    assert not p.has_clearance(CLEARANCE_PEOPLE_NAMES)


# --- label modes (D3.9) --------------------------------------------------------


def test_label_modes_ride_in_the_policy() -> None:
    p = policy(
        label_modes={
            "business_name": ("bucket", 3),
            "person_name": ("pseudonymise", 5),
            "category": ("suppress", 5),  # never masked: not carried
        }
    )
    assert p.mask_mode("business_name") == LabelMode("bucket", 3)
    assert p.mask_mode("person_name") == LabelMode("pseudonymise", 5)
    assert p.mask_mode("category") is None


@pytest.mark.parametrize(
    "setting", [("shred", 5), ("bucket", 0), ("bucket", 51), ("suppress", -1)]
)
def test_invalid_label_modes_are_left_out(setting: tuple[str, int]) -> None:
    p = policy(label_modes={"person_name": setting})
    assert p.mask_mode("person_name") is None  # the atlas then suppresses


def test_mask_mode_unknown_class_is_none() -> None:
    p = policy(label_modes={"person_name": ("suppress", 5)})
    assert p.mask_mode("planet_name") is None
    assert Policy.deny_all(USER, "ygg", 1).mask_mode("person_name") is None


def test_label_mode_defaults_to_five_buckets() -> None:
    assert LabelMode("bucket").bucket_size == 5

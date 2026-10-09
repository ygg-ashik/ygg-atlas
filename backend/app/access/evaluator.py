"""Evaluates one user's access from plain facts (spec §5.4). Pure: no I/O, no clock."""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from uuid import UUID

import structlog

from app.access.catalog import CAPABILITIES, role_capabilities
from app.access.facts import (
    EFFECT_ALLOW,
    EFFECT_DENY,
    KIND_CAPABILITY,
    KIND_CLEARANCE,
    KIND_RESOURCE,
    STANDING_MANAGER,
    STATUS_ACTIVE,
    SUBJECT_GROUP,
    SUBJECT_USER,
    GrantFacts,
    GroupFacts,
    PolicyInputs,
)
from app.access.patterns import InvalidPatternError, validate_pattern
from app.access.policy import Policy, Rule

type Groups = Mapping[UUID, GroupFacts]

logger = structlog.get_logger()

_VALID_EFFECTS = frozenset({EFFECT_ALLOW, EFFECT_DENY})
_VALID_TARGET_KINDS = frozenset({KIND_RESOURCE, KIND_CAPABILITY, KIND_CLEARANCE})


def evaluate(inputs: PolicyInputs, now: datetime) -> Policy:
    if now.tzinfo is None:
        msg = "evaluate() needs an aware datetime"
        raise ValueError(msg)
    user = inputs.user
    if user.status != STATUS_ACTIVE:
        return Policy.deny_all(user.id, user.tenant, inputs.policy_version, user.role)
    groups = {gid: g for gid, g in inputs.groups.items() if g.tenant == user.tenant}
    member_of = frozenset(gid for gid in inputs.memberships if gid in groups)
    reach = with_ancestors(member_of, groups)
    grants = [g for g in inputs.grants if _applies(g, user.id, reach) and _live(g, now)]
    allow, deny = _resource_rules(grants, groups)
    # A corrupt grant also drops manager rights.
    managed: set[UUID] = (
        set()
        if any(_is_malformed(g) for g in grants)
        else {g for g in member_of if inputs.memberships[g] == STANDING_MANAGER}
    )
    expiries = [g.expires_at for g in grants if g.expires_at is not None]
    return Policy(
        user_id=user.id,
        tenant=user.tenant,
        role=user.role,
        active=True,
        policy_version=inputs.policy_version,
        capabilities=_capabilities(user.role, grants),
        allow_rules=allow,
        deny_rules=deny,
        group_ids=member_of,
        managed_group_ids=_with_descendants(managed, groups),
        valid_until=min(expiries, default=None),
    )


def _live(grant: GrantFacts, now: datetime) -> bool:
    return grant.expires_at is None or grant.expires_at > now


def _applies(grant: GrantFacts, user_id: UUID, reach: frozenset[UUID]) -> bool:
    # subject_type is constrained by a CHECK in the database (migration 0003);
    # an unknown type applies to nobody.
    if grant.subject_type == SUBJECT_USER:
        return grant.subject_id == user_id
    return grant.subject_type == SUBJECT_GROUP and grant.subject_id in reach


def _is_malformed(grant: GrantFacts) -> bool:
    return (
        grant.effect not in _VALID_EFFECTS
        or grant.target_kind not in _VALID_TARGET_KINDS
    )


def restricts(grant: GrantFacts, now: datetime) -> bool:
    """True when `grant` is live and narrows access: a deny, or a malformed
    grant (which the evaluator turns into deny-all). Removing someone from a
    group that carries such a grant widens their access."""
    return _live(grant, now) and (grant.effect == EFFECT_DENY or _is_malformed(grant))


def with_ancestors(start: Iterable[UUID], groups: Groups) -> frozenset[UUID]:
    """The groups plus every ancestor. Cycle-safe: a group is visited once."""
    seen: set[UUID] = set()
    for gid in start:
        current: UUID | None = gid
        while current is not None and current in groups and current not in seen:
            seen.add(current)
            current = groups[current].parent_id
    return frozenset(seen)


def _with_descendants(roots: Iterable[UUID], groups: Groups) -> frozenset[UUID]:
    children: dict[UUID, list[UUID]] = {}
    for group in groups.values():
        if group.parent_id is not None:
            children.setdefault(group.parent_id, []).append(group.id)
    seen: set[UUID] = set()
    stack = list(roots)
    while stack:
        gid = stack.pop()
        if gid not in seen:
            seen.add(gid)
            stack.extend(children.get(gid, ()))
    return frozenset(seen)


def _capabilities(role: str, grants: Sequence[GrantFacts]) -> frozenset[str]:
    """Role bundle + direct user allows - direct user denies (spec §5.4 step 1)."""
    # A corrupt grant drops every capability, as it drops data access in
    # _resource_rules and manager rights in evaluate().
    if any(_is_malformed(g) for g in grants):
        return frozenset()
    overrides = [
        g
        for g in grants
        if g.subject_type == SUBJECT_USER
        and g.target_kind == KIND_CAPABILITY
        # Retired capabilities are ignored (spec §5.1); Task 8 rejects unknown
        # targets on write.
        and g.target in CAPABILITIES
    ]
    allowed = {g.target for g in overrides if g.effect == EFFECT_ALLOW}
    denied = {g.target for g in overrides if g.effect == EFFECT_DENY}
    return frozenset((role_capabilities(role) | allowed) - denied)


def _rule_key(rule: Rule) -> tuple[int, int, str, str]:
    """Most specific first: more segments, fewer wildcards, then pattern, then id."""
    segments = rule.pattern.split("/")
    wildcards = sum(1 for s in segments if s == "*")
    return -len(segments), wildcards, rule.pattern, str(rule.grant_id)


def _origin(grant: GrantFacts, groups: Groups) -> str:
    if grant.subject_type == SUBJECT_USER:
        return "user"
    return f"group:{groups[grant.subject_id].name}"


def _resource_rules(
    grants: Sequence[GrantFacts], groups: Groups
) -> tuple[tuple[Rule, ...], tuple[Rule, ...]]:
    allow: list[Rule] = []
    deny: list[Rule] = []
    for g in grants:
        origin = _origin(g, groups)
        # A corrupt grant fails closed: no data, no capabilities and no
        # manager rights; the reason names the grant.
        if _is_malformed(g):
            logger.warning(
                "access.malformed_grant",
                grant_id=str(g.id),
                effect=g.effect,
                target_kind=g.target_kind,
            )
            deny.append(Rule("*", g.id, origin))
            continue
        if g.target_kind != KIND_RESOURCE:
            continue  # valid capability grants go to _capabilities; clearance: D1
        try:
            validate_pattern(g.target)
        except InvalidPatternError:
            if g.effect == EFFECT_DENY:
                logger.warning(
                    "access.invalid_deny_pattern", grant_id=str(g.id), target=g.target
                )
                deny.append(Rule("*", g.id, origin))
            else:
                logger.warning(
                    "access.invalid_allow_pattern",
                    grant_id=str(g.id),
                    target=g.target,
                )
            continue
        (deny if g.effect == EFFECT_DENY else allow).append(
            Rule(g.target, g.id, origin)
        )
    return tuple(sorted(allow, key=_rule_key)), tuple(sorted(deny, key=_rule_key))

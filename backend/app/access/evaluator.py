"""Evaluates one user's access from plain facts (spec §5.4). Pure: no I/O, no clock."""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from types import MappingProxyType
from typing import cast
from uuid import UUID

import structlog

from app.access.catalog import CAPABILITIES, CLEARANCES, role_capabilities
from app.access.facts import (
    EFFECT_ALLOW,
    EFFECT_DENY,
    KIND_CAPABILITY,
    KIND_CLEARANCE,
    KIND_RESOURCE,
    MASK_MODES,
    MASKABLE_LABEL_CLASSES,
    MAX_BUCKET_SIZE,
    MAX_SCOPE_DIMENSIONS,
    MAX_SCOPE_VALUES,
    SCOPE_KEY,
    SELF_TOKEN,
    STANDING_MANAGER,
    STATUS_ACTIVE,
    SUBJECT_GROUP,
    SUBJECT_USER,
    GrantFacts,
    GroupFacts,
    PolicyInputs,
)
from app.access.patterns import InvalidPatternError, validate_pattern
from app.access.policy import Conjunction, LabelMode, Policy, Rule, SkippedRule

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
    allow, deny, skipped = _resource_rules(grants, groups, inputs)
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
        clearances=_clearances(grants),
        label_modes=_label_modes(inputs.label_modes),
        skipped=skipped,
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
    # Groups never grant capabilities (spec §5.2); the API refuses to write
    # one, so a group capability grant came from direct SQL. Ignoring it would
    # silently drop a deny, so it fails closed like any other corrupt grant.
    return (
        grant.effect not in _VALID_EFFECTS
        or grant.target_kind not in _VALID_TARGET_KINDS
        or (
            grant.subject_type == SUBJECT_GROUP and grant.target_kind == KIND_CAPABILITY
        )
        or _malformed_scope(grant)
    )


def _malformed_scope(grant: GrantFacts) -> bool:
    """D3.3: a row scope that is not a well-formed `{dimension: [values]}` on a
    resource allow."""
    if grant.row_scope is None:
        return False
    if grant.effect != EFFECT_ALLOW or grant.target_kind != KIND_RESOURCE:
        return True  # row-scoped denies are out of scope (spec §15)
    return not _well_formed_scope(grant.row_scope)


def _well_formed_scope(scope: object) -> bool:
    # The column is JSON: check the stored shape, never trust the annotation.
    if not isinstance(scope, Mapping):
        return False
    items = cast("Mapping[object, object]", scope)
    return 1 <= len(items) <= MAX_SCOPE_DIMENSIONS and all(
        isinstance(key, str) and SCOPE_KEY.fullmatch(key) and _well_formed_values(v)
        for key, v in items.items()
    )


def _well_formed_values(values: object) -> bool:
    if isinstance(values, str) or not isinstance(values, Sequence):
        return False
    items = cast("Sequence[object]", values)
    return 1 <= len(items) <= MAX_SCOPE_VALUES and all(
        isinstance(v, str) and v for v in items
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


def _clearances(grants: Sequence[GrantFacts]) -> frozenset[str]:
    """Clearance allows minus clearance denies, from user and group grants.
    Unknown codes are ignored; a corrupt grant drops them all (fail closed)."""
    if any(_is_malformed(g) for g in grants):
        return frozenset()
    targets = [
        g for g in grants if g.target_kind == KIND_CLEARANCE and g.target in CLEARANCES
    ]
    allowed = {g.target for g in targets if g.effect == EFFECT_ALLOW}
    denied = {g.target for g in targets if g.effect == EFFECT_DENY}
    return frozenset(allowed - denied)


def _label_modes(stored: Mapping[str, tuple[str, int]]) -> Mapping[str, LabelMode]:
    """Valid settings only; anything else is left out and the atlas suppresses."""
    return MappingProxyType(
        {
            label_class: LabelMode(mode, size)
            for label_class, (mode, size) in stored.items()
            if label_class in MASKABLE_LABEL_CLASSES
            and mode in MASK_MODES
            and 1 <= size <= MAX_BUCKET_SIZE
        }
    )


def _resolve_scope(
    scope: Mapping[str, Sequence[str]], inputs: PolicyInputs
) -> Conjunction | str:
    """The grant's concrete conjunction, or the reason `$self` can't resolve."""
    pairs: list[tuple[str, frozenset[str]]] = []
    for dimension, values in sorted(scope.items()):
        concrete = set(values)
        if SELF_TOKEN in concrete:
            attribute = inputs.self_attributes.get(dimension)
            if attribute is None:
                return f"dimension '{dimension}' has no $self attribute"
            value = inputs.attributes.get(attribute, "")
            if not value:
                return f"missing attribute '{attribute}'"
            concrete.discard(SELF_TOKEN)
            concrete.add(value)
        pairs.append((dimension, frozenset(concrete)))
    return tuple(pairs)


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
    grants: Sequence[GrantFacts], groups: Groups, inputs: PolicyInputs
) -> tuple[tuple[Rule, ...], tuple[Rule, ...], tuple[SkippedRule, ...]]:
    allow: list[Rule] = []
    deny: list[Rule] = []
    skipped: list[SkippedRule] = []
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
                scoped=g.row_scope is not None,
            )
            deny.append(Rule("*", g.id, origin))
            continue
        if g.target_kind != KIND_RESOURCE:
            continue  # valid capability / clearance grants are evaluated apart
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
        if g.effect == EFFECT_DENY:
            deny.append(Rule(g.target, g.id, origin))
            continue
        scope = None if g.row_scope is None else _resolve_scope(g.row_scope, inputs)
        if isinstance(scope, str):
            # A per-user condition, not corruption: only this grant drops out.
            logger.warning(
                "access.scope_self_unresolved", grant_id=str(g.id), reason=scope
            )
            skipped.append(SkippedRule(g.target, g.id, origin, scope))
            continue
        allow.append(Rule(g.target, g.id, origin, scope))
    return (
        tuple(sorted(allow, key=_rule_key)),
        tuple(sorted(deny, key=_rule_key)),
        tuple(sorted(skipped, key=lambda r: (r.pattern, str(r.grant_id)))),
    )

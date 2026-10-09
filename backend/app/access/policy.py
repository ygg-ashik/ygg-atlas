"""The evaluated access of one user at one policy_version (spec §2).

It is the only object enforcement code consults. Immutable, so it is safe to cache.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Self
from uuid import UUID

from app.access.catalog import ADMIN_GROUPS
from app.access.patterns import matches

NO_GRANT = "no grant allows it"

# One grant's row scope: sorted (dimension, values) pairs, ANDed. Concrete
# values only ($self is resolved by the evaluator); hashable.
type Conjunction = tuple[tuple[str, frozenset[str]], ...]
# What the atlas compiles: alternatives ORed. () means no rows.
type RowScope = tuple[dict[str, frozenset[str]], ...]


@dataclass(frozen=True, slots=True)
class Rule:
    pattern: str
    grant_id: UUID
    origin: str  # "user", or "group:<name>"
    scope: Conjunction | None = None  # None = all rows


@dataclass(frozen=True, slots=True)
class SkippedRule:
    """An allow left out for this user, e.g. its `$self` attribute is unset."""

    pattern: str
    grant_id: UUID
    origin: str
    reason: str


@dataclass(frozen=True, slots=True)
class LabelMode:
    """How a label class is shown without its clearance (spec §5.6)."""

    mode: str  # one of facts.MASK_MODES
    bucket_size: int = 5


def _no_label_modes() -> Mapping[str, LabelMode]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    rule: Rule | None = None  # the deny that won, or the allow that matched

    @property
    def reason(self) -> str:
        if self.rule is None:
            return NO_GRANT
        verb = "allowed" if self.allowed else "denied"
        return f"{verb} by grant {self.rule.grant_id} ({self.rule.origin})"


@dataclass(frozen=True, slots=True)
class Policy:
    user_id: UUID
    tenant: str
    role: str
    active: bool
    policy_version: int
    capabilities: frozenset[str] = frozenset()
    allow_rules: tuple[Rule, ...] = ()
    deny_rules: tuple[Rule, ...] = ()
    group_ids: frozenset[UUID] = frozenset()
    managed_group_ids: frozenset[UUID] = frozenset()
    valid_until: datetime | None = None  # earliest expiry among the grants used
    clearances: frozenset[str] = frozenset()
    label_modes: Mapping[str, LabelMode] = field(default_factory=_no_label_modes)
    skipped: tuple[SkippedRule, ...] = ()

    @classmethod
    def deny_all(
        cls, user_id: UUID, tenant: str, policy_version: int, role: str = ""
    ) -> Self:
        return cls(
            user_id=user_id,
            tenant=tenant,
            role=role,
            active=False,
            policy_version=policy_version,
        )

    def has(self, capability: str) -> bool:
        return self.active and capability in self.capabilities

    def decide(self, resource: str) -> Decision:
        if not self.active:
            return Decision(allowed=False)
        for rule in self.deny_rules:
            if matches(rule.pattern, resource):
                return Decision(allowed=False, rule=rule)
        for rule in self.allow_rules:
            if matches(rule.pattern, resource):
                return Decision(allowed=True, rule=rule)
        return Decision(allowed=False)

    def row_scope(self, resource: str) -> RowScope | None:
        """Which rows of an allowed resource (D3.3): `None` = all rows, else the
        alternatives ORed; `()` = denied. Every matching allow counts, not only
        the most specific one, and any unscoped one wins."""
        if not self.decide(resource).allowed:
            return ()
        matching = [r for r in self.allow_rules if matches(r.pattern, resource)]
        conjunctions: list[Conjunction] = []
        for rule in matching:
            if rule.scope is None:
                return None
            conjunctions.append(rule.scope)
        return tuple(dict(c) for c in dict.fromkeys(conjunctions))

    def has_clearance(self, clearance: str) -> bool:
        return self.active and clearance in self.clearances

    def mask_mode(self, label_class: str) -> LabelMode | None:
        """`None` = no valid setting; the atlas then suppresses (fail closed)."""
        return self.label_modes.get(label_class)

    def allows(self, resource: str) -> bool:
        return self.decide(resource).allowed

    def deny_reason(self, resource: str) -> str:
        return self.decide(resource).reason

    @property
    def has_data_access(self) -> bool:
        """True when at least one allow rule exists (a deny may still cover it);
        use allows() for decisions."""
        return self.active and bool(self.allow_rules)

    def can_manage_members(self, group_id: UUID) -> bool:
        """Caller must ensure the group is in this policy's tenant."""
        if self.has(ADMIN_GROUPS):
            return True
        return self.active and group_id in self.managed_group_ids

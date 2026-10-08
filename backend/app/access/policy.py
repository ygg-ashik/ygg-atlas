"""The evaluated access of one user at one policy_version (spec §2).

It is the only object enforcement code consults. Immutable, so it is safe to cache.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Self
from uuid import UUID

from app.access.catalog import ADMIN_GROUPS
from app.access.patterns import matches

NO_GRANT = "no grant allows it"


@dataclass(frozen=True, slots=True)
class Rule:
    pattern: str
    grant_id: UUID
    origin: str  # "user", or "group:<name>"


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

    def allows(self, resource: str) -> bool:
        return self.decide(resource).allowed

    def deny_reason(self, resource: str) -> str:
        return self.decide(resource).reason

    @property
    def has_data_access(self) -> bool:
        return self.active and bool(self.allow_rules)

    def can_manage_members(self, group_id: UUID) -> bool:
        if self.has(ADMIN_GROUPS):
            return True
        return self.active and group_id in self.managed_group_ids

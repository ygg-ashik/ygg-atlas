"""A user's evaluated access, as the admin preview shows it."""

from typing import Self
from uuid import UUID

from pydantic import BaseModel

from app.access.policy import Conjunction, Policy, RowScope, Rule, SkippedRule


def _scope_out(conjunction: Conjunction) -> dict[str, list[str]]:
    return {dimension: sorted(values) for dimension, values in conjunction}


def _row_scope_out(scope: RowScope | None) -> list[dict[str, list[str]]] | None:
    if scope is None:
        return None
    return [{d: sorted(v) for d, v in sorted(alt.items())} for alt in scope]


class RuleOut(BaseModel):
    pattern: str
    grant_id: UUID
    origin: str
    # None = all rows. `$self` already resolved to the user's attribute value.
    row_scope: dict[str, list[str]] | None = None

    @classmethod
    def of(cls, rule: Rule) -> Self:
        return cls(
            pattern=rule.pattern,
            grant_id=rule.grant_id,
            origin=rule.origin,
            row_scope=None if rule.scope is None else _scope_out(rule.scope),
        )


class SkippedOut(BaseModel):
    pattern: str
    grant_id: UUID
    origin: str
    reason: str

    @classmethod
    def of(cls, rule: SkippedRule) -> Self:
        return cls(
            pattern=rule.pattern,
            grant_id=rule.grant_id,
            origin=rule.origin,
            reason=rule.reason,
        )


class DecisionOut(BaseModel):
    resource: str
    allowed: bool
    reason: str
    # None = all rows; else the alternatives ORed; [] = no rows.
    row_scope: list[dict[str, list[str]]] | None


class EffectiveAccessOut(BaseModel):
    user_id: UUID
    role: str
    active: bool
    capabilities: list[str]
    allow: list[RuleOut]
    deny: list[RuleOut]
    decision: DecisionOut | None
    clearances: list[str]
    skipped: list[SkippedOut]

    @classmethod
    def from_policy(cls, policy: Policy, resource: str | None) -> Self:
        """The policy view of a user's access. `decision.row_scope` is what the
        policy grants; the atlas additionally drops any dimension the entity
        does not declare, so execution may be narrower, never wider."""
        decision = None
        if resource:
            verdict = policy.decide(resource)
            decision = DecisionOut(
                resource=resource,
                allowed=verdict.allowed,
                reason=verdict.reason,
                row_scope=_row_scope_out(policy.row_scope(resource)),
            )
        return cls(
            user_id=policy.user_id,
            role=policy.role,
            active=policy.active,
            capabilities=sorted(policy.capabilities),
            allow=[RuleOut.of(r) for r in policy.allow_rules],
            deny=[RuleOut.of(r) for r in policy.deny_rules],
            decision=decision,
            clearances=sorted(policy.clearances) if policy.active else [],
            skipped=[SkippedOut.of(r) for r in policy.skipped],
        )

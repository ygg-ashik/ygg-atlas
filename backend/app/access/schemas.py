"""Request and response shapes for the access API (separate from the tables)."""

from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.access.catalog import CAPABILITIES, CLEARANCES, ROLES, role_capabilities
from app.access.facts import (
    LABEL_CLASSES,
    MASK_MODES,
    MAX_ATTRIBUTE_VALUE,
    MAX_BUCKET_SIZE,
    MAX_SCOPE_DIMENSIONS,
    MAX_SCOPE_VALUES,
    SCOPE_KEY,
    is_well_formed_scope,
)
from app.access.policy import Conjunction, Policy, RowScope, Rule, SkippedRule


class GroupRefOut(BaseModel):
    id: UUID
    name: str
    standing: str


class MeAccessOut(BaseModel):
    role: str
    capabilities: list[str]
    groups: list[GroupRefOut]
    has_data_access: bool
    clearances: list[str]


class CapabilityOut(BaseModel):
    code: str
    description: str


class RoleOut(BaseModel):
    name: str
    capabilities: list[str]


class ClearanceOut(BaseModel):
    code: str
    description: str


class CatalogOut(BaseModel):
    capabilities: list[CapabilityOut]
    roles: list[RoleOut]
    clearances: list[ClearanceOut]
    # The YAML vocabulary; maskable classes come from GET /admin/label-classes.
    label_classes: list[str]
    mask_modes: list[str]

    @classmethod
    def build(cls) -> Self:
        return cls(
            capabilities=[
                CapabilityOut(code=code, description=text)
                for code, text in CAPABILITIES.items()
            ],
            roles=[
                RoleOut(name=role, capabilities=sorted(role_capabilities(role)))
                for role in ROLES
            ],
            clearances=[
                ClearanceOut(code=code, description=text)
                for code, text in CLEARANCES.items()
            ],
            label_classes=list(LABEL_CLASSES),
            mask_modes=list(MASK_MODES),
        )


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    parent_id: UUID | None = None


class GroupUpdate(BaseModel):
    """Only the fields sent are changed; send `parent_id: null` to make a root group."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    parent_id: UUID | None = None


class MemberPut(BaseModel):
    standing: Literal["member", "manager"] = "member"


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    standing: str
    added_at: datetime


class GrantCreate(BaseModel):
    subject_type: Literal["group", "user"]
    subject_id: UUID
    effect: Literal["allow", "deny"] = "allow"
    target_kind: Literal["resource", "capability", "clearance"] = "resource"
    target: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=500)
    expires_at: AwareDatetime | None = None
    # None = all rows; else {dimension: [values]}, `$self` allowed (spec §5.5).
    row_scope: dict[str, list[str]] | None = None

    @field_validator("row_scope")
    @classmethod
    def _normalized_scope(
        cls, scope: dict[str, list[str]] | None
    ) -> dict[str, list[str]] | None:
        return None if scope is None else _normalize_scope(scope)


def _normalize_scope(scope: dict[str, list[str]]) -> dict[str, list[str]]:
    """Validate a row scope and return it with sorted keys and de-duplicated,
    sorted values. Never returns a scope the evaluator would treat as
    malformed (D3.3): `is_well_formed_scope` is the final word."""
    if not 1 <= len(scope) <= MAX_SCOPE_DIMENSIONS:
        msg = f"A row scope names 1 to {MAX_SCOPE_DIMENSIONS} dimensions."
        raise ValueError(msg)
    normalized: dict[str, list[str]] = {}
    for key in sorted(scope):
        values = [v.strip() for v in scope[key]]
        if not SCOPE_KEY.fullmatch(key):
            msg = (
                f"'{key}' is not a scope dimension name: up to 64 lowercase "
                "letters, digits and underscores, starting with a letter."
            )
            raise ValueError(msg)
        if not 1 <= len(values) <= MAX_SCOPE_VALUES:
            msg = f"Scope '{key}' needs 1 to {MAX_SCOPE_VALUES} values."
            raise ValueError(msg)
        if any(not 1 <= len(v) <= MAX_ATTRIBUTE_VALUE for v in values):
            msg = (
                f"Each value of scope '{key}' is 1 to {MAX_ATTRIBUTE_VALUE} characters."
            )
            raise ValueError(msg)
        normalized[key] = sorted(set(values))
    if not is_well_formed_scope(normalized):
        msg = "That row scope is not valid."
        raise ValueError(msg)
    return normalized


class AttributePut(BaseModel):
    value: str = Field(min_length=1, max_length=MAX_ATTRIBUTE_VALUE)


class LabelClassPut(BaseModel):
    mode: Literal["pseudonymise", "suppress", "bucket"]
    bucket_size: int | None = Field(default=None, ge=1, le=MAX_BUCKET_SIZE)


class AttributeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: str
    set_by: UUID | None
    set_at: datetime


class LabelClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label_class: str
    mode: str
    bucket_size: int
    updated_at: datetime


class ScopeDimensionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    entity: str
    dimension: str
    self_attribute: str | None
    description: str


class UserUpdate(BaseModel):
    """Only the fields sent are changed; at least one must be present."""

    role: str | None = None
    status: Literal["active", "disabled"] | None = None


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    parent_id: UUID | None
    created_at: datetime


class GrantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_type: str
    subject_id: UUID
    effect: str
    target_kind: str
    target: str
    reason: str
    expires_at: datetime | None
    created_by: UUID | None
    created_at: datetime
    row_scope: dict[str, list[str]] | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    kind: str
    role: str
    status: str
    last_seen_at: datetime | None


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
        does not declare (D3.7), so execution may be narrower, never wider."""
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


class ChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_user_id: UUID | None
    via: str
    action: str
    object_type: str
    object_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    at: datetime

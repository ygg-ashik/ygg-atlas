"""Request and response shapes for the access API (separate from the tables)."""

from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.access.catalog import CAPABILITIES, ROLES, role_capabilities
from app.access.policy import Policy, Rule


class GroupRefOut(BaseModel):
    id: UUID
    name: str
    standing: str


class MeAccessOut(BaseModel):
    role: str
    capabilities: list[str]
    groups: list[GroupRefOut]
    has_data_access: bool


class CapabilityOut(BaseModel):
    code: str
    description: str


class RoleOut(BaseModel):
    name: str
    capabilities: list[str]


class CatalogOut(BaseModel):
    capabilities: list[CapabilityOut]
    roles: list[RoleOut]

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


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    kind: str
    role: str
    status: str
    last_seen_at: datetime | None


class RuleOut(BaseModel):
    pattern: str
    grant_id: UUID
    origin: str

    @classmethod
    def of(cls, rule: Rule) -> Self:
        return cls(pattern=rule.pattern, grant_id=rule.grant_id, origin=rule.origin)


class DecisionOut(BaseModel):
    resource: str
    allowed: bool
    reason: str


class EffectiveAccessOut(BaseModel):
    user_id: UUID
    role: str
    active: bool
    capabilities: list[str]
    allow: list[RuleOut]
    deny: list[RuleOut]
    decision: DecisionOut | None

    @classmethod
    def from_policy(cls, policy: Policy, resource: str | None) -> Self:
        decision = None
        if resource:
            verdict = policy.decide(resource)
            decision = DecisionOut(
                resource=resource, allowed=verdict.allowed, reason=verdict.reason
            )
        return cls(
            user_id=policy.user_id,
            role=policy.role,
            active=policy.active,
            capabilities=sorted(policy.capabilities),
            allow=[RuleOut.of(r) for r in policy.allow_rules],
            deny=[RuleOut.of(r) for r in policy.deny_rules],
            decision=decision,
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

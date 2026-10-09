"""Request and response shapes for the access API (separate from the tables)."""

from datetime import date, datetime
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
    user_id: UUID
    email: str
    display_name: str
    pending_requests: int  # the caller's own
    pending_approvals: int  # the caller may decide (never their own; P5-D9)
    is_manager: bool


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
    role: str
    status: str


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
    created_at: datetime


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


class ActorRefOut(BaseModel):
    """Who made a change (admin:audit views only)."""

    display_name: str
    email: str


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
    actor: ActorRefOut | None = None  # None: CLI, bootstrap, or a user since removed


class Page[T](BaseModel):
    """One page of a keyset-paged list; `next_cursor` is None on the last page."""

    items: list[T]
    next_cursor: str | None = None


class AccessRequestCreate(BaseModel):
    kind: Literal["group", "role", "resource"]
    target: str = Field(min_length=1, max_length=200)
    # Stripped by the service; a blank note is refused there (422).
    note: str = Field(min_length=1, max_length=500)


class RequestDecision(BaseModel):
    note: str = Field(default="", max_length=500)
    # Absent, explicit null and a value mean different things (P5-D12): read
    # presence through `model_fields_set`.
    expires_at: AwareDatetime | None = None


class RequesterOut(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    role: str


class DeciderOut(BaseModel):
    user_id: UUID | None  # None: decided from the CLI
    display_name: str


class AccessRequestOut(BaseModel):
    id: UUID
    kind: str
    target: str
    target_label: str
    note: str
    status: str
    created_at: datetime
    decided_by: DeciderOut | None
    decided_at: datetime | None
    decision_note: str
    requester: RequesterOut | None = None  # admin views only


class RequestGroupOptionOut(BaseModel):
    id: UUID
    name: str
    managers: list[str]  # display names only, never emails


class RequestOptionsOut(BaseModel):
    resource: str
    groups: list[RequestGroupOptionOut]
    can_request_resource: bool


# ---- audit views (admin:audit; phase 5) ----------------------------------------


class ChangeQuery(BaseModel):
    """One page of the change log: keyset position, size and filters. Also
    the route's query-parameter model, so the bounds live in one place."""

    model_config = ConfigDict(frozen=True)

    cursor: str | None = Field(default=None, max_length=512)
    limit: int = Field(default=100, ge=1, le=200)
    actor_user_id: UUID | None = None
    object_type: str | None = Field(default=None, min_length=1, max_length=32)
    action: str | None = Field(default=None, min_length=1, max_length=64)
    object_id: str | None = Field(default=None, min_length=1, max_length=100)
    since: AwareDatetime | None = None  # inclusive
    until: AwareDatetime | None = None  # exclusive


class DecisionQuery(BaseModel):
    """One page of the atlas decision log: keyset position, size and filters.
    Also the route's query-parameter model."""

    model_config = ConfigDict(frozen=True)

    cursor: str | None = Field(default=None, max_length=512)
    limit: int = Field(default=100, ge=1, le=200)
    user_id: UUID | None = None
    decision: Literal["allow", "deny"] | None = None
    surface: str | None = Field(default=None, min_length=1, max_length=16)
    tool: str | None = Field(default=None, min_length=1, max_length=100)
    auth_method: str | None = Field(default=None, min_length=1, max_length=16)
    since: AwareDatetime | None = None  # inclusive
    until: AwareDatetime | None = None  # exclusive


class AuditUserOut(BaseModel):
    user_id: UUID
    email: str
    display_name: str


class AuditDecisionOut(BaseModel):
    """One atlas tool call and its policy decision (P5-D15)."""

    id: UUID
    user: AuditUserOut
    auth_method: str | None
    surface: str
    tool: str
    arguments: dict[str, Any] | None
    decision: str
    deny_reason: str | None
    success: bool
    error: str | None
    duration_ms: int | None
    created_at: datetime


class DayCountOut(BaseModel):
    date: date  # UTC day
    allow: int
    deny: int


class ReasonCountOut(BaseModel):
    reason: str
    count: int


class UserCountOut(BaseModel):
    user_id: UUID
    display_name: str  # never an email
    count: int


class AuditSummaryOut(BaseModel):
    days: int
    per_day: list[DayCountOut]
    top_deny_reasons: list[ReasonCountOut]
    top_denied_users: list[UserCountOut]


# ---- user and group detail, the user list (phase 5, B5) -------------------------


class UserQuery(BaseModel):
    """One page of the user list: search, filters, keyset position on
    (email, id) and size. Also the route's query-parameter model."""

    model_config = ConfigDict(frozen=True)

    q: str = Field(default="", max_length=100)  # email or display name; stripped
    role: str | None = Field(default=None, min_length=1, max_length=32)
    status: Literal["active", "disabled"] | None = None
    kind: Literal["human", "service"] | None = None
    cursor: str | None = Field(default=None, max_length=512)
    limit: int = Field(default=50, ge=1, le=200)


class UserGroupOut(BaseModel):
    id: UUID
    name: str
    standing: str


class UserDetailOut(UserOut):
    groups: list[UserGroupOut]  # direct memberships, by name
    direct_grants: list[GrantOut]
    pending_requests: int


class GroupDetailOut(GroupOut):
    member_count: int  # direct members
    grant_count: int  # grants held by this group itself
    path: list[str]  # names, root first, ending with this group


class MemberCandidateOut(BaseModel):
    """A colleague a group's managers may add (P5-D21)."""

    user_id: UUID
    display_name: str
    email: str

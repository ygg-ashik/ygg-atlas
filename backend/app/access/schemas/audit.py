"""Audit views (admin:audit): the access-change log and atlas tool decisions."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


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

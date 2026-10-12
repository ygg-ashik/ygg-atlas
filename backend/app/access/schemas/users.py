"""Users: the list query, the row and detail shapes, and role/status updates."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.access.schemas.grants import GrantOut


class UserUpdate(BaseModel):
    """Only the fields sent are changed; at least one must be present."""

    role: str | None = None
    status: Literal["active", "disabled"] | None = None


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

"""Groups and their members: create, update, detail and membership shapes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    parent_id: UUID | None = None


class GroupUpdate(BaseModel):
    """Only the fields sent are changed; send `parent_id: null` to make a root group."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    parent_id: UUID | None = None


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    parent_id: UUID | None
    created_at: datetime


class GroupDetailOut(GroupOut):
    member_count: int  # direct members
    grant_count: int  # grants held by this group itself
    path: list[str]  # names, root first, ending with this group


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


class MemberCandidateOut(BaseModel):
    """A colleague a group's managers may add (P5-D21)."""

    user_id: UUID
    display_name: str
    email: str

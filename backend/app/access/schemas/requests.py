"""Access requests: the ask, the decision and the request shapes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field


class AccessRequestCreate(BaseModel):
    kind: Literal["group", "role", "resource"]
    target: str = Field(min_length=1, max_length=200)
    # Stripped by the service; a blank note is refused there (422).
    note: str = Field(min_length=1, max_length=500)


class RequestDecision(BaseModel):
    note: str = Field(default="", max_length=500)
    # Absent, explicit null and a value mean different things: read
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

"""What the caller sees about themselves: /me/access and the capability catalog."""

from typing import Self
from uuid import UUID

from pydantic import BaseModel

from app.access.catalog import CAPABILITIES, CLEARANCES, ROLES, role_capabilities
from app.access.facts import LABEL_CLASSES, MASK_MODES


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
    pending_approvals: int  # the caller may decide (never their own)
    is_manager: bool
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

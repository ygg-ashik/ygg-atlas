"""Plain inputs to the evaluator (spec §5.4) and the access vocabulary.

No database, HTTP or clock here: the repository builds these, the evaluator reads them.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

SUBJECT_GROUP: Final = "group"
SUBJECT_USER: Final = "user"
EFFECT_ALLOW: Final = "allow"
EFFECT_DENY: Final = "deny"
KIND_RESOURCE: Final = "resource"
KIND_CAPABILITY: Final = "capability"
KIND_CLEARANCE: Final = "clearance"  # phase 3; ignored until then (decision D1)
STANDING_MEMBER: Final = "member"
STANDING_MANAGER: Final = "manager"
DEFAULT_TENANT: Final = "ygg"


@dataclass(frozen=True, slots=True)
class UserFacts:
    id: UUID
    role: str
    status: str
    tenant: str


@dataclass(frozen=True, slots=True)
class GroupFacts:
    id: UUID
    name: str
    parent_id: UUID | None
    tenant: str


@dataclass(frozen=True, slots=True)
class GrantFacts:
    id: UUID
    subject_type: str
    subject_id: UUID
    effect: str
    target_kind: str
    target: str
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class PolicyInputs:
    user: UserFacts
    groups: Mapping[UUID, GroupFacts]  # every group in the user's tenant
    memberships: Mapping[UUID, str]  # group id -> standing, for this user
    grants: Sequence[GrantFacts]  # grants on this user and on the tenant's groups
    policy_version: int

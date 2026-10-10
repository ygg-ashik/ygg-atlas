"""Plain inputs to the evaluator (spec §5.4) and the access vocabulary.

No database, HTTP or clock here: the repository builds these, the evaluator reads them.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, cast
from uuid import UUID

SUBJECT_GROUP: Final = "group"
SUBJECT_USER: Final = "user"
EFFECT_ALLOW: Final = "allow"
EFFECT_DENY: Final = "deny"
KIND_RESOURCE: Final = "resource"
KIND_CAPABILITY: Final = "capability"
KIND_CLEARANCE: Final = "clearance"
STANDING_MEMBER: Final = "member"
STANDING_MANAGER: Final = "manager"
DEFAULT_TENANT: Final = "ygg"
STATUS_ACTIVE: Final = "active"

# Breakdown label classes and how admins may mask them (spec §5.6); the
# clearance codes live with the capability codes in catalog.py.
LABEL_CLASSES: Final[tuple[str, ...]] = ("category", "business_name", "person_name")
MASKABLE_LABEL_CLASSES: Final[tuple[str, ...]] = ("business_name", "person_name")
MASK_MODES: Final[tuple[str, ...]] = ("pseudonymise", "suppress", "bucket")
MAX_BUCKET_SIZE: Final = 50

# Row scopes (spec §5.5): `{dimension: [values]}` on a resource allow.
SELF_TOKEN: Final = "$self"  # noqa: S105  # the $self placeholder, not a secret
BUILTIN_ATTRIBUTES: Final[tuple[str, ...]] = ("email", "user_id")
MAX_SCOPE_DIMENSIONS: Final = 20
MAX_SCOPE_VALUES: Final = 100
MAX_ATTRIBUTE_VALUE: Final = 200
SCOPE_KEY: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


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
    # None = all rows; else dimension -> values (values may hold SELF_TOKEN).
    row_scope: Mapping[str, Sequence[str]] | None = None


@dataclass(frozen=True, slots=True)
class PolicyInputs:
    user: UserFacts
    groups: Mapping[UUID, GroupFacts]  # every group in the user's tenant
    memberships: Mapping[UUID, str]  # group id -> standing, for this user
    grants: Sequence[GrantFacts]  # grants on this user and on the tenant's groups
    policy_version: int
    # user_attributes rows plus the BUILTIN_ATTRIBUTES; feeds `$self`.
    attributes: Mapping[str, str] = field(default_factory=dict[str, str])
    # dimension -> the attribute its `$self` resolves to (the scope_dimensions mirror).
    self_attributes: Mapping[str, str] = field(default_factory=dict[str, str])
    # label class -> (mode, bucket_size), as stored by admins.
    label_modes: Mapping[str, tuple[str, int]] = field(
        default_factory=dict[str, tuple[str, int]]
    )


def as_utc(moment: datetime | None) -> datetime | None:
    """Normalize a stored timestamp to UTC-aware.

    SQLite returns naive datetimes even for columns declared
    `TIMESTAMP(timezone=True)`; every stored timestamp is UTC end-to-end
    (CLAUDE.md), so a naive value is always UTC. A `None` or already-aware
    value is returned unchanged.
    """
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=UTC)


def is_well_formed_scope(scope: object) -> bool:
    """D3.3: True for a `{dimension: [values]}` the evaluator can apply.

    The one shape check shared by the evaluator (a stored scope that fails it
    makes its grant malformed, i.e. deny-all) and the admin API (which never
    stores one that fails it). The column is JSON: check the actual shape,
    never trust the annotation.
    """
    if not isinstance(scope, Mapping):
        return False
    items = cast("Mapping[object, object]", scope)
    return 1 <= len(items) <= MAX_SCOPE_DIMENSIONS and all(
        isinstance(key, str)
        and SCOPE_KEY.fullmatch(key) is not None
        and _well_formed_values(values)
        for key, values in items.items()
    )


def _well_formed_values(values: object) -> bool:
    if isinstance(values, str) or not isinstance(values, Sequence):
        return False
    items = cast("Sequence[object]", values)
    return 1 <= len(items) <= MAX_SCOPE_VALUES and all(
        isinstance(v, str) and v for v in items
    )

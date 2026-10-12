"""The rules of access requests that need no database: limits, statuses,
messages, who may decide what (`decidable_scope`, P5-D9) and the approval
expiry (P5-D12), and which groups would grant a resource."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from app.access.actor import Actor
from app.access.catalog import ROLES
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.evaluator import evaluate
from app.access.facts import (
    KIND_RESOURCE,
    STANDING_MEMBER,
    STATUS_ACTIVE,
    SUBJECT_GROUP,
    GrantFacts,
    GroupFacts,
    PolicyInputs,
    UserFacts,
)
from app.access.models import AccessRequest
from app.access.policy import DecidableScope, Policy, decidable_scope
from app.access.schemas import RequestDecision

MAX_PENDING: Final = 20
OWN_LIST_LIMIT: Final = 100
DEFAULT_RESOURCE_EXPIRY: Final = timedelta(days=90)
MAX_REASON: Final = 500

PENDING: Final = "pending"
APPROVED: Final = "approved"
DECLINED: Final = "declined"
CANCELLED: Final = "cancelled"
DECIDED: Final = "decided"  # a queue filter, not a stored status
STATUS_SETS: Final[Mapping[str, tuple[str, ...]]] = {DECIDED: (APPROVED, DECLINED)}

KIND_GROUP: Final = "group"
KIND_ROLE: Final = "role"
ITEM_SEGMENTS: Final = 3  # source/entity/item: the only requestable resource

NO_SUCH_REQUEST: Final = "No such request."
ALREADY_DECIDED: Final = "This request was already decided."
OWN_REQUEST: Final = "You can't decide your own request."
REQUESTER_DISABLED: Final = "The requester's account is disabled."
NOT_ACTIVE: Final = "Only active accounts can request access."
NO_SCOPE: Final = "This needs admin:users, admin:groups or group manager standing."
DUPLICATE: Final = "You already asked for this; it's pending."

# A member-shaped stand-in for "anyone who joins this group" (groups_granting).
_PROBE_USER: Final = UUID(int=0)


def groups_granting(
    resource: str,
    groups: Mapping[UUID, GroupFacts],
    grants: Sequence[GrantFacts],
    now: datetime,
) -> list[UUID]:
    """Groups whose members would be allowed `resource` through the group
    alone, judged exactly as the evaluator judges a member: own and ancestor
    live allows, beaten by any live deny (or malformed grant) that matches.

    Pure. Only group grants count; returned sorted by group name.
    """
    group_grants = [g for g in grants if g.subject_type == SUBJECT_GROUP]
    granting: list[GroupFacts] = []
    for group in groups.values():
        probe = PolicyInputs(
            user=UserFacts(_PROBE_USER, "", STATUS_ACTIVE, group.tenant),
            groups=groups,
            memberships={group.id: STANDING_MEMBER},
            grants=group_grants,
            policy_version=0,
        )
        if evaluate(probe, now).allows(resource):
            granting.append(group)
    return [g.id for g in sorted(granting, key=lambda g: (g.name, str(g.id)))]


def role_rank(role: str) -> int:
    """Position in ROLES; an unknown role ranks below every real one."""
    return ROLES.index(role) if role in ROLES else -1


def decidable_scope_of(actor: Actor) -> DecidableScope:
    if actor.policy is None:
        return DecidableScope.everything()
    return decidable_scope(actor.policy)


def require_active(policy: Policy) -> None:
    if not policy.active:
        raise AccessDeniedError(NOT_ACTIVE)


def expiry_present(decision: RequestDecision) -> bool:
    return "expires_at" in decision.model_fields_set


def check_decidable(actor: Actor, request: AccessRequest | None) -> AccessRequest:
    if request is None or request.tenant != actor.tenant:
        raise NotFoundError(NO_SUCH_REQUEST)
    if actor.user_id is not None and request.user_id == actor.user_id:
        raise ConflictError(OWN_REQUEST)
    if not decidable_scope_of(actor).covers(
        request.kind, request.target, request.user_id
    ):
        raise NotFoundError(NO_SUCH_REQUEST)
    return request


def approval_expiry(
    request: AccessRequest, decision: RequestDecision, now: datetime
) -> datetime | None:
    """P5-D12: absent → now + 90 days; null → none; a value must be future."""
    if request.kind != KIND_RESOURCE:
        if expiry_present(decision):
            msg = "An expiry only applies to a resource request."
            raise InvalidChangeError(msg)
        return None
    if not expiry_present(decision):
        return now + DEFAULT_RESOURCE_EXPIRY
    if decision.expires_at is not None and decision.expires_at <= now:
        msg = "The expiry must be in the future."
        raise InvalidChangeError(msg)
    return decision.expires_at

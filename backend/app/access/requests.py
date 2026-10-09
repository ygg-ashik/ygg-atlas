"""Access requests (spec §3.2 step 4, phase 5): ask, cancel, decide.

A user asks for a group, a role or one exact resource. Create, cancel and
decline change no access, so they write only `access_requests`: no
`rbac_changes` row and no policy_version bump, and request traffic never
evicts cached policies. An approval is one unit of work under
`AccessAdmin._write`: the request is re-read under the lock, the access change
is staged through the same helper a direct admin write uses (so D8 and D10
run unchanged), and the access change plus a `request.approve` row commit with
one version bump.

Who decides what is one pure function, `decidable_scope` (P5-D9); a request
outside the caller's scope reads as "No such request." (P5-D10).
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import structlog
from sqlalchemy.exc import IntegrityError

from app.access.admin import AccessAdmin, Actor, page_position
from app.access.catalog import ROLES
from app.access.cursor import time_page
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.evaluator import evaluate
from app.access.facts import (
    EFFECT_ALLOW,
    KIND_RESOURCE,
    STANDING_MEMBER,
    STATUS_ACTIVE,
    SUBJECT_GROUP,
    SUBJECT_USER,
    GrantFacts,
    GroupFacts,
    PolicyInputs,
    UserFacts,
    as_utc,
)
from app.access.models import AccessRequest, RbacChange
from app.access.patterns import is_resource_path
from app.access.policy import DecidableScope, Policy, decidable_scope
from app.access.schemas import (
    AccessRequestCreate,
    AccessRequestOut,
    DeciderOut,
    GrantCreate,
    Page,
    RequestDecision,
    RequesterOut,
    RequestGroupOptionOut,
    RequestOptionsOut,
    UserUpdate,
)
from app.identity import User

logger = structlog.get_logger()

MAX_PENDING: Final = 20
OWN_LIST_LIMIT: Final = 100
DEFAULT_RESOURCE_EXPIRY: Final = timedelta(days=90)
MAX_REASON: Final = 500
CLI_DECIDER: Final = "atlas CLI"

PENDING: Final = "pending"
APPROVED: Final = "approved"
DECLINED: Final = "declined"
CANCELLED: Final = "cancelled"
DECIDED: Final = "decided"  # a queue filter, not a stored status
_STATUS_SETS: Final[Mapping[str, tuple[str, ...]]] = {DECIDED: (APPROVED, DECLINED)}

KIND_GROUP: Final = "group"
KIND_ROLE: Final = "role"

NO_SUCH_REQUEST: Final = "No such request."
ALREADY_DECIDED: Final = "This request was already decided."
OWN_REQUEST: Final = "You can't decide your own request."
REQUESTER_DISABLED: Final = "The requester's account is disabled."
NOT_ACTIVE: Final = "Only active accounts can request access."
NO_SCOPE: Final = "This needs admin:users, admin:groups or group manager standing."
DUPLICATE: Final = "You already asked for this; it's pending."

# A member-shaped stand-in for "anyone who joins this group" (groups_granting).
_PROBE_USER: Final = UUID(int=0)


def _utcnow() -> datetime:
    return datetime.now(UTC)


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


def _aware(moment: datetime) -> datetime:
    """A stored timestamp as UTC-aware (SQLite returns naive UTC)."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _role_rank(role: str) -> int:
    """Position in ROLES; an unknown role ranks below every real one."""
    return ROLES.index(role) if role in ROLES else -1


def _scope(actor: Actor) -> DecidableScope:
    if actor.policy is None:
        return DecidableScope.everything()
    return decidable_scope(actor.policy)


def _require_active(policy: Policy) -> None:
    if not policy.active:
        raise AccessDeniedError(NOT_ACTIVE)


def _expiry_present(decision: RequestDecision) -> bool:
    return "expires_at" in decision.model_fields_set


class AccessRequests(AccessAdmin):
    """The request lifecycle. Subclasses AccessAdmin to reuse its staged,
    lock-holding write helpers without widening AccessAdmin's public API."""

    # ---- the requester ------------------------------------------------------

    async def create(
        self, policy: Policy, payload: AccessRequestCreate
    ) -> AccessRequestOut:
        _require_active(policy)
        note = payload.note.strip()
        if not note:
            msg = "Say why you need this access."
            raise InvalidChangeError(msg)
        try:
            # The row lock makes the pending cap atomic per user (Postgres).
            user = await self._repo.lock_user(policy.user_id)
            if (
                user is None
                or user.tenant != policy.tenant
                or user.status != STATUS_ACTIVE
            ):
                raise AccessDeniedError(NOT_ACTIVE)
            target = await self._valid_target(user, payload.kind, payload.target)
            if await self._repo.count_pending(user.id) >= MAX_PENDING:
                msg = (
                    f"You have {MAX_PENDING} pending requests; cancel one or wait "
                    "for a decision first."
                )
                raise InvalidChangeError(msg)
            if await self._repo.pending_request(user.id, payload.kind, target):
                raise ConflictError(DUPLICATE)
            request = AccessRequest(
                tenant=policy.tenant,
                user_id=user.id,
                kind=payload.kind,
                target=target,
                note=note,
            )
            self._repo.add(request)
            await self._repo.commit()
        except IntegrityError:
            # Two creates raced past the pre-check: the partial unique index won.
            await self._repo.rollback()
            raise ConflictError(DUPLICATE) from None
        except Exception:
            await self._repo.rollback()
            raise
        logger.info(
            "access.request_created", request_id=str(request.id), kind=request.kind
        )
        return await self._out(request)

    async def cancel(self, policy: Policy, request_id: UUID) -> AccessRequestOut:
        _require_active(policy)
        request = await self._repo.request(request_id)
        if (
            request is None
            or request.tenant != policy.tenant
            or request.user_id != policy.user_id
        ):
            raise NotFoundError(NO_SUCH_REQUEST)
        try:
            changed = await self._repo.finish_request(
                request_id,
                policy.tenant,
                CANCELLED,
                decided_by=policy.user_id,
                note="",
                requester=policy.user_id,
            )
            await self._repo.commit()
        except Exception:
            await self._repo.rollback()
            raise
        if not changed:
            raise ConflictError(ALREADY_DECIDED)
        logger.info("access.request_cancelled", request_id=str(request_id))
        return await self._reloaded(request_id)

    async def list_own(self, policy: Policy) -> list[AccessRequestOut]:
        _require_active(policy)
        rows = await self._repo.list_own_requests(
            policy.tenant, policy.user_id, OWN_LIST_LIMIT
        )
        return await self._outs([(r, None) for r in rows], policy.tenant)

    async def options(self, policy: Policy, resource: str) -> RequestOptionsOut:
        """Groups that would grant `resource` to a new member, with their
        managers' display names (P5-D13), for the request form."""
        _require_active(policy)
        if not is_resource_path(resource):
            msg = f"'{resource}' is not a resource path like demo/order/revenue."
            raise InvalidChangeError(msg)
        groups = await self._repo.tenant_groups(policy.tenant)
        grants = await self._repo.all_group_grants(policy.tenant)
        ids = [
            gid
            for gid in groups_granting(resource, groups, grants, _utcnow())
            if gid not in policy.group_ids
        ]
        managers = await self._repo.group_managers(ids)
        return RequestOptionsOut(
            resource=resource,
            groups=[
                RequestGroupOptionOut(
                    id=gid, name=groups[gid].name, managers=managers.get(gid, [])
                )
                for gid in ids
            ],
            can_request_resource=not policy.allows(resource),
        )

    # ---- the decider --------------------------------------------------------

    async def list_decidable(
        self,
        actor: Actor,
        status: str | None,
        cursor: str | None,
        limit: int,
        *,
        user_id: UUID | None = None,
    ) -> Page[AccessRequestOut]:
        """Requests the actor may decide, newest first. `status` is one status,
        `decided` (approved or declined; P5-D23) or None for every status;
        `user_id` narrows to one requester, still inside the scope (P5-D24)."""
        scope = _scope(actor)
        if scope.empty:
            raise AccessDeniedError(NO_SCOPE)
        statuses = _STATUS_SETS.get(status, (status,)) if status is not None else None
        rows = await self._repo.list_decidable(
            actor.tenant,
            scope,
            statuses,
            page_position(cursor),
            limit,
            user_id=user_id,
        )
        page, next_cursor = time_page(rows, limit, lambda r: (r[0].created_at, r[0].id))
        items = await self._outs(page, actor.tenant)
        return Page[AccessRequestOut](items=items, next_cursor=next_cursor)

    async def approve(
        self, actor: Actor, request_id: UUID, decision: RequestDecision
    ) -> AccessRequestOut:
        await self._decidable_request(actor, request_id)  # fail fast, no lock
        note = decision.note.strip()
        async with self._write(actor):
            request = await self._locked_pending(actor, request_id)
            await self._requester_active(request)
            now = _utcnow()
            expires_at = self._approval_expiry(request, decision, now)
            access_change = await self._stage_access(actor, request, expires_at, now)
            after: dict[str, Any] = {
                "status": APPROVED,
                "kind": request.kind,
                "target": request.target,
                "user_id": str(request.user_id),
            }
            if request.kind == KIND_RESOURCE:
                after["expires_at"] = (
                    None if expires_at is None else expires_at.isoformat()
                )
            request.status = APPROVED
            request.decided_by = actor.user_id
            request.decided_at = now
            request.decision_note = note
            self._repo.add(request)
            request_change = RbacChange(
                actor_user_id=actor.user_id,
                via=actor.via,
                tenant=actor.tenant,
                action="request.approve",
                object_type="access_request",
                object_id=str(request.id),
                before={"status": PENDING},
                after=after,
            )
            changes = [c for c in (access_change, request_change) if c is not None]
            await self._commit(*changes)
        return await self._reloaded(request_id, with_requester=True)

    async def decline(
        self, actor: Actor, request_id: UUID, decision: RequestDecision
    ) -> AccessRequestOut:
        if _expiry_present(decision):
            msg = "An expiry only applies when approving a resource request."
            raise InvalidChangeError(msg)
        await self._decidable_request(actor, request_id)
        note = decision.note.strip()
        # The lock re-checks the decider's authority (stale actor: 409), but a
        # decline changes no access: no rbac_changes row, no version bump.
        async with self._write(actor):
            await self._locked_pending(actor, request_id)
            changed = await self._repo.finish_request(
                request_id, actor.tenant, DECLINED, decided_by=actor.user_id, note=note
            )
            if not changed:
                raise ConflictError(ALREADY_DECIDED)
            await self._repo.commit()
        logger.info(
            "access.request_declined",
            request_id=str(request_id),
            actor_user_id=str(actor.user_id),
        )
        return await self._reloaded(request_id, with_requester=True)

    # ---- helpers ------------------------------------------------------------

    async def _valid_target(self, user: User, kind: str, target: str) -> str:
        """The canonical target for a new request, or a 422 (P5-D11)."""
        if kind == KIND_GROUP:
            return await self._valid_group_target(user, target)
        if kind == KIND_ROLE:
            if target not in ROLES:
                msg = f"Unknown role '{target}'. Roles: {', '.join(ROLES)}."
                raise InvalidChangeError(msg)
            if _role_rank(target) <= _role_rank(user.role):
                msg = f"You already have the {user.role} role; ask for a higher one."
                raise InvalidChangeError(msg)
            return target
        if not is_resource_path(target):
            msg = (
                f"'{target}' is not a resource path like demo/order/revenue; "
                "request one exact resource."
            )
            raise InvalidChangeError(msg)
        return target

    async def _valid_group_target(self, user: User, target: str) -> str:
        try:
            group_id = UUID(target)
        except ValueError:
            group_id = None
        group = None if group_id is None else await self._repo.group(group_id)
        if group is None or group.tenant != user.tenant:
            msg = "No such group."
            raise InvalidChangeError(msg)
        if await self._repo.member(group.id, user.id) is not None:
            msg = f"You're already in {group.name}."
            raise InvalidChangeError(msg)
        return str(group.id)

    async def _decidable_request(self, actor: Actor, request_id: UUID) -> None:
        """404 unless the request is in the actor's view; 409 if it is theirs."""
        request = await self._repo.request(request_id)
        self._check_decidable(actor, request)

    def _check_decidable(
        self, actor: Actor, request: AccessRequest | None
    ) -> AccessRequest:
        if request is None or request.tenant != actor.tenant:
            raise NotFoundError(NO_SUCH_REQUEST)
        if actor.user_id is not None and request.user_id == actor.user_id:
            raise ConflictError(OWN_REQUEST)
        if not _scope(actor).covers(request.kind, request.target, request.user_id):
            raise NotFoundError(NO_SUCH_REQUEST)
        return request

    async def _locked_pending(self, actor: Actor, request_id: UUID) -> AccessRequest:
        """Re-read the request under the caller's `_write`; it must still be
        in view and pending."""
        request = self._check_decidable(
            actor, await self._repo.request_for_update(request_id)
        )
        if request.status != PENDING:
            raise ConflictError(ALREADY_DECIDED)
        return request

    async def _requester_active(self, request: AccessRequest) -> None:
        """Fail closed: never grant access to an account disabled since it asked."""
        requester = await self._repo.user(request.user_id)
        if requester is None or requester.status != STATUS_ACTIVE:
            raise ConflictError(REQUESTER_DISABLED)

    def _approval_expiry(
        self, request: AccessRequest, decision: RequestDecision, now: datetime
    ) -> datetime | None:
        """P5-D12: absent → now + 90 days; null → none; a value must be future."""
        if request.kind != KIND_RESOURCE:
            if _expiry_present(decision):
                msg = "An expiry only applies to a resource request."
                raise InvalidChangeError(msg)
            return None
        if not _expiry_present(decision):
            return now + DEFAULT_RESOURCE_EXPIRY
        if decision.expires_at is not None and decision.expires_at <= now:
            msg = "The expiry must be in the future."
            raise InvalidChangeError(msg)
        return decision.expires_at

    async def _stage_access(
        self,
        actor: Actor,
        request: AccessRequest,
        expires_at: datetime | None,
        now: datetime,
    ) -> RbacChange | None:
        """Stage the access the request asks for; None when it is already held
        (an approval never demotes or duplicates, P5-D7)."""
        if request.kind == KIND_GROUP:
            group_id = UUID(request.target)
            if await self._repo.member(group_id, request.user_id) is not None:
                await self._group(actor, group_id)
                return None  # already in, at any standing
            _, change = await self._stage_member(
                actor, group_id, request.user_id, STANDING_MEMBER
            )
            return change
        if request.kind == KIND_ROLE:
            user = await self._user(actor, request.user_id)
            if _role_rank(user.role) >= _role_rank(request.target):
                return None  # already at or above the requested role
            _, change = await self._stage_user_update(
                actor, request.user_id, UserUpdate(role=request.target)
            )
            return change
        existing = await self._repo.find_grant(
            (SUBJECT_USER, request.user_id), EFFECT_ALLOW, KIND_RESOURCE, request.target
        )
        expiry = None if existing is None else as_utc(existing.expires_at)
        if existing is not None and (expiry is None or expiry > now):
            return None  # an identical live allow already exists
        reason = f"Access request {request.id}: {request.note}"[:MAX_REASON]
        payload = GrantCreate(
            subject_type=SUBJECT_USER,
            subject_id=request.user_id,
            effect=EFFECT_ALLOW,
            target_kind=KIND_RESOURCE,
            target=request.target,
            reason=reason,
            expires_at=expires_at,
        )
        _, change = await self._stage_grant(actor, payload, now)
        return change

    async def _reloaded(
        self, request_id: UUID, *, with_requester: bool = False
    ) -> AccessRequestOut:
        request = await self._repo.request(request_id)
        if request is None:  # pragma: no cover - committed just before
            raise NotFoundError(NO_SUCH_REQUEST)
        return await self._out(request, with_requester=with_requester)

    async def _out(
        self, request: AccessRequest, *, with_requester: bool = False
    ) -> AccessRequestOut:
        """One request; `with_requester` embeds the requester (decider views)."""
        requester = await self._repo.user(request.user_id) if with_requester else None
        [out] = await self._outs([(request, requester)], request.tenant)
        return out

    async def _outs(
        self, rows: Sequence[tuple[AccessRequest, User | None]], tenant: str
    ) -> list[AccessRequestOut]:
        """Shape requests; `requester` is set only where a row carries one
        (admin views)."""
        groups = await self._repo.tenant_groups(tenant)
        deciders = await self._repo.users_by_id(
            r.decided_by for r, _ in rows if r.decided_by is not None
        )
        outs: list[AccessRequestOut] = []
        for request, requester in rows:
            label = request.target
            if request.kind == KIND_GROUP:
                try:
                    group = groups.get(UUID(request.target))
                except ValueError:
                    group = None
                label = group.name if group is not None else request.target
            decided_by = None
            if request.status != PENDING:
                decider = (
                    None
                    if request.decided_by is None
                    else deciders.get(request.decided_by)
                )
                decided_by = DeciderOut(
                    user_id=request.decided_by,
                    display_name=(
                        CLI_DECIDER
                        if request.decided_by is None
                        else (decider.display_name if decider is not None else "")
                    ),
                )
            outs.append(
                AccessRequestOut(
                    id=request.id,
                    kind=request.kind,
                    target=request.target,
                    target_label=label,
                    note=request.note,
                    status=request.status,
                    created_at=_aware(request.created_at),
                    decided_by=decided_by,
                    decided_at=as_utc(request.decided_at),
                    decision_note=request.decision_note,
                    requester=None
                    if requester is None
                    else RequesterOut(
                        user_id=requester.id,
                        email=requester.email,
                        display_name=requester.display_name,
                        role=requester.role,
                    ),
                )
            )
        return outs

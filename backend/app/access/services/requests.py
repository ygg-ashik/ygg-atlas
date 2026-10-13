"""Access requests: ask, cancel, decide.

A user asks for a group, a role or one exact resource. Create, cancel and
decline change no access, so they write only `access_requests`: no
`rbac_changes` row and no policy_version bump, and request traffic never
evicts cached policies. An approval is one unit of work under the shared
`AccessWriter`: the request is re-read under the lock, the access change is
staged through the same topic-service helper a direct admin write uses (so the
manager-standing and no-self-widening checks run unchanged), and the access
change plus a `request.approve` row commit with one version bump.

Who decides what is one pure function, `decidable_scope`; a request
outside the caller's scope reads as "No such request."
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.exc import IntegrityError

from app.access.actor import Actor
from app.access.catalog import ROLES
from app.access.cursor import time_page
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.facts import (
    EFFECT_ALLOW,
    KIND_RESOURCE,
    STANDING_MEMBER,
    STATUS_ACTIVE,
    SUBJECT_USER,
    as_utc,
)
from app.access.models import AccessRequest, RbacChange
from app.access.patterns import is_resource_path
from app.access.policy import Policy
from app.access.repositories import AccessRepository
from app.access.schemas import (
    AccessRequestCreate,
    AccessRequestOut,
    GrantCreate,
    Page,
    RequestDecision,
    RequestGroupOptionOut,
    RequestOptionsOut,
    UserUpdate,
)
from app.access.service import AccessService
from app.access.services.grants import GrantService
from app.access.services.lookup import TenantLookup
from app.access.services.members import MemberService
from app.access.services.paging import page_position
from app.access.services.request_rules import (
    ALREADY_DECIDED,
    APPROVED,
    CANCELLED,
    DECLINED,
    DUPLICATE,
    ITEM_SEGMENTS,
    KIND_GROUP,
    KIND_ROLE,
    MAX_PENDING,
    MAX_REASON,
    NO_SCOPE,
    NO_SUCH_REQUEST,
    NOT_ACTIVE,
    OWN_LIST_LIMIT,
    PENDING,
    REQUESTER_DISABLED,
    STATUS_SETS,
    approval_expiry,
    check_decidable,
    decidable_scope_of,
    expiry_present,
    groups_granting,
    require_active,
    role_rank,
)
from app.access.services.request_views import RequestViews
from app.access.services.users import UserService
from app.access.services.writer import AccessWriter
from app.identity import User

logger = structlog.get_logger()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RequestService:
    """The request lifecycle. Approvals stage access through the member,
    user and grant services and commit through the shared writer."""

    def __init__(
        self,
        repo: AccessRepository,
        access: AccessService,
        writer: AccessWriter,
        members: MemberService,
        users: UserService,
        grants: GrantService,
    ) -> None:
        self._repo = repo
        self._writer = writer
        self._lookup = TenantLookup(repo)
        self._access = access
        self._members = members
        self._users = users
        self._grants = grants
        self._views = RequestViews(repo)

    async def create(
        self, policy: Policy, payload: AccessRequestCreate
    ) -> AccessRequestOut:
        require_active(policy)
        note = payload.note.strip()
        if not note:
            msg = "Say why you need this access."
            raise InvalidChangeError(msg)
        try:
            # The row lock makes the pending cap atomic per user (Postgres).
            user = await self._repo.users.lock_user(policy.user_id)
            if (
                user is None
                or user.tenant != policy.tenant
                or user.status != STATUS_ACTIVE
            ):
                raise AccessDeniedError(NOT_ACTIVE)
            target = await self._valid_target(user, payload.kind, payload.target)
            if payload.kind == KIND_RESOURCE and policy.allows(target):
                # Already allowed (maybe row-scoped): an unscoped direct grant
                # would silently lift the scope, so there is nothing to request.
                msg = f"You can already see {target}."
                raise InvalidChangeError(msg)
            if await self._repo.requests.count_pending(user.id) >= MAX_PENDING:
                msg = (
                    f"You have {MAX_PENDING} pending requests; cancel one or wait "
                    "for a decision first."
                )
                raise InvalidChangeError(msg)
            if await self._repo.requests.pending_request(user.id, payload.kind, target):
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
        return await self._views.out(request)

    async def cancel(self, policy: Policy, request_id: UUID) -> AccessRequestOut:
        require_active(policy)
        request = await self._repo.requests.request(request_id)
        if (
            request is None
            or request.tenant != policy.tenant
            or request.user_id != policy.user_id
        ):
            raise NotFoundError(NO_SUCH_REQUEST)
        try:
            changed = await self._repo.requests.finish_request(
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
        return await self._views.reloaded(request_id)

    async def list_own(self, policy: Policy) -> list[AccessRequestOut]:
        require_active(policy)
        rows = await self._repo.requests.list_own_requests(
            policy.tenant, policy.user_id, OWN_LIST_LIMIT
        )
        return await self._views.outs([(r, None) for r in rows], policy.tenant)

    async def options(self, policy: Policy, resource: str) -> RequestOptionsOut:
        """Groups that would grant `resource` to a new member, with their
        managers' display names, for the request form."""
        require_active(policy)
        if not is_resource_path(resource):
            msg = f"'{resource}' is not a resource path like demo/order/revenue."
            raise InvalidChangeError(msg)
        groups = await self._repo.groups.tenant_groups(policy.tenant)
        grants = await self._repo.grants.all_group_grants(policy.tenant)
        ids = [
            gid
            for gid in groups_granting(resource, groups, grants, _utcnow())
            if gid not in policy.group_ids
        ]
        managers = await self._repo.groups.group_managers(ids)
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
        `decided` (approved or declined) or None for every status;
        `user_id` narrows to one requester, still inside the scope."""
        scope = decidable_scope_of(actor)
        if scope.empty:
            raise AccessDeniedError(NO_SCOPE)
        statuses = STATUS_SETS.get(status, (status,)) if status is not None else None
        rows = await self._repo.requests.list_decidable(
            actor.tenant,
            scope,
            statuses,
            page_position(cursor),
            limit,
            user_id=user_id,
        )
        page, next_cursor = time_page(rows, limit, lambda r: (r[0].created_at, r[0].id))
        items = await self._views.outs(page, actor.tenant)
        return Page[AccessRequestOut](items=items, next_cursor=next_cursor)

    async def approve(
        self, actor: Actor, request_id: UUID, decision: RequestDecision
    ) -> AccessRequestOut:
        await self._decidable_request(actor, request_id)  # fail fast, no lock
        note = decision.note.strip()
        async with self._writer.write(actor):
            request = await self._locked_pending(actor, request_id)
            await self._requester_active(request)
            now = _utcnow()
            expires_at = approval_expiry(request, decision, now)
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
            await self._writer.commit(*changes)
        return await self._views.reloaded(request_id, with_requester=True)

    async def decline(
        self, actor: Actor, request_id: UUID, decision: RequestDecision
    ) -> AccessRequestOut:
        if expiry_present(decision):
            msg = "An expiry only applies when approving a resource request."
            raise InvalidChangeError(msg)
        await self._decidable_request(actor, request_id)
        note = decision.note.strip()
        # The lock re-checks the decider's authority (stale actor: 409), but a
        # decline changes no access: no rbac_changes row, no version bump.
        async with self._writer.write(actor):
            await self._locked_pending(actor, request_id)
            changed = await self._repo.requests.finish_request(
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
        return await self._views.reloaded(request_id, with_requester=True)

    async def _valid_target(self, user: User, kind: str, target: str) -> str:
        """The canonical target for a new request, or a 422."""
        if kind == KIND_GROUP:
            return await self._valid_group_target(user, target)
        if kind == KIND_ROLE:
            if target not in ROLES:
                msg = f"Unknown role '{target}'. Roles: {', '.join(ROLES)}."
                raise InvalidChangeError(msg)
            if role_rank(target) <= role_rank(user.role):
                msg = f"You already have the {user.role} role; ask for a higher one."
                raise InvalidChangeError(msg)
            return target
        # One exact item only: an entity or source path could never be approved
        # (grants on those need a '/*' pattern, which would widen the request).
        if not is_resource_path(target) or len(target.split("/")) != ITEM_SEGMENTS:
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
        group = None if group_id is None else await self._repo.groups.group(group_id)
        if group is None or group.tenant != user.tenant:
            msg = "No such group."
            raise InvalidChangeError(msg)
        if await self._repo.groups.member(group.id, user.id) is not None:
            msg = f"You're already in {group.name}."
            raise InvalidChangeError(msg)
        return str(group.id)

    async def _decidable_request(self, actor: Actor, request_id: UUID) -> None:
        """404 unless the request is in the actor's view; 409 if it is theirs."""
        request = await self._repo.requests.request(request_id)
        check_decidable(actor, request)

    async def _locked_pending(self, actor: Actor, request_id: UUID) -> AccessRequest:
        """Re-read the request under the caller's `AccessWriter.write`; it must
        still be in view and pending."""
        request = check_decidable(
            actor, await self._repo.requests.request_for_update(request_id)
        )
        if request.status != PENDING:
            raise ConflictError(ALREADY_DECIDED)
        return request

    async def _requester_active(self, request: AccessRequest) -> None:
        """Fail closed: never grant access to an account disabled since it asked."""
        requester = await self._repo.users.user(request.user_id)
        if requester is None or requester.status != STATUS_ACTIVE:
            raise ConflictError(REQUESTER_DISABLED)

    async def _stage_access(
        self,
        actor: Actor,
        request: AccessRequest,
        expires_at: datetime | None,
        now: datetime,
    ) -> RbacChange | None:
        """Stage the access the request asks for; None when it is already held
        (an approval never demotes or duplicates)."""
        if request.kind == KIND_GROUP:
            group_id = UUID(request.target)
            if await self._repo.groups.member(group_id, request.user_id) is not None:
                await self._lookup.group(actor, group_id)
                return None  # already in, at any standing
            _, change = await self._members.stage_member(
                actor, group_id, request.user_id, STANDING_MEMBER
            )
            return change
        if request.kind == KIND_ROLE:
            user = await self._lookup.user(actor, request.user_id)
            if role_rank(user.role) >= role_rank(request.target):
                return None  # already at or above the requested role
            _, change = await self._users.stage_user_update(
                actor, request.user_id, UserUpdate(role=request.target)
            )
            return change
        return await self._stage_resource(actor, request, expires_at, now)

    async def _stage_resource(
        self,
        actor: Actor,
        request: AccessRequest,
        expires_at: datetime | None,
        now: datetime,
    ) -> RbacChange | None:
        """Stage the exact resource grant; None when the requester can already
        see it. Allowed since the request was made (possibly row-scoped) makes
        the approval a no-op: an unscoped grant would silently lift the scope."""
        requester = await self._access.policy_for_user(request.user_id)
        if requester.allows(request.target):
            return None
        existing = await self._repo.grants.find_grant(
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
        _, change = await self._grants.stage_grant(actor, payload, now)
        return change

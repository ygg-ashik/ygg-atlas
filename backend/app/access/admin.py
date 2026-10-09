"""Administration of access (spec §5, §10): groups, members, grants, roles, status.

Each write is one unit of work: the change, its rbac_changes row and the
policy_version bump commit together, so no cached policy can miss a change.
Every write also locks `policy_state` first (`AccessRepository.lock_for_write`),
so concurrent admin writes serialize and a losing write sees a 409 instead of
racing past another write's application-level checks; under that lock the
actor's policy_version must still be current, or the write is a 409 too.

A failed write rolls the session back, which expires loaded objects; reload
them before reuse.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Final, Literal, Self
from uuid import UUID

import structlog
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel

from app.access.catalog import (
    ADMIN_AUDIT,
    ADMIN_GROUPS,
    ADMIN_USERS,
    CAPABILITIES,
    ROLES,
    role_capabilities,
)
from app.access.cursor import (
    InvalidCursorError,
    decode_cursor,
    decode_time_cursor,
    encode_cursor,
    time_page,
)
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.evaluator import restricts, with_ancestors
from app.access.facts import (
    DEFAULT_TENANT,
    EFFECT_DENY,
    KIND_CAPABILITY,
    KIND_CLEARANCE,
    STANDING_MANAGER,
    STANDING_MEMBER,
    SUBJECT_GROUP,
    SUBJECT_USER,
    as_utc,
)
from app.access.models import Grant, Group, GroupMember, RbacChange
from app.access.patterns import InvalidPatternError, validate_pattern
from app.access.policy import Policy
from app.access.repository import AccessRepository
from app.access.schemas import (
    ActorRefOut,
    AuditDecisionOut,
    AuditSummaryOut,
    AuditUserOut,
    ChangeOut,
    ChangeQuery,
    DayCountOut,
    DecisionQuery,
    GrantCreate,
    GrantOut,
    GroupCreate,
    GroupDetailOut,
    GroupOut,
    GroupUpdate,
    MemberCandidateOut,
    MemberOut,
    Page,
    ReasonCountOut,
    UserCountOut,
    UserDetailOut,
    UserGroupOut,
    UserOut,
    UserQuery,
    UserUpdate,
)
from app.access.service import AccessService
from app.identity import TokenVerifier, User, UserKind, UserStatus
from app.models.audit import AtlasAuditLog

logger = structlog.get_logger()


BAD_CURSOR: Final = "That page link is invalid; reload the list."
_ALL_CHANGES: Final = ChangeQuery()
_ALL_DECISIONS: Final = DecisionQuery()
_TOP: Final = 5  # top deny reasons and denied users in the summary
_NO_REASON: Final = "unspecified"
MAX_CANDIDATES: Final = 10  # member-candidate lookup (P5-D21)
CANDIDATE_QUERY: Final = (3, 100)  # stripped length bounds


def page_position(cursor: str | None) -> tuple[datetime, UUID] | None:
    """A request's cursor as a UTC keyset position; a bad one is a 422 (P5-D16)."""
    if cursor is None:
        return None
    try:
        return decode_time_cursor(cursor)
    except InvalidCursorError:
        raise InvalidChangeError(BAD_CURSOR) from None


def _email_position(cursor: str | None) -> tuple[str, UUID] | None:
    """A user-list cursor as an (email, id) keyset position; a bad one is a 422."""
    if cursor is None:
        return None
    try:
        return decode_cursor(cursor)
    except InvalidCursorError:
        raise InvalidChangeError(BAD_CURSOR) from None


def _actor_ref(user: User | None) -> ActorRefOut | None:
    if user is None:
        return None
    return ActorRefOut(display_name=user.display_name, email=user.email)


def _decision_out(entry: AtlasAuditLog, user: User) -> AuditDecisionOut:
    # The owner keys are replaced by the user ref; the session id stays private.
    fields = entry.model_dump(exclude={"user_uid", "user_id", "session_id"})
    user_ref = AuditUserOut(
        user_id=user.id, email=user.email, display_name=user.display_name
    )
    return AuditDecisionOut.model_validate({**fields, "user": user_ref})


def _snapshot(row: SQLModel | None) -> dict[str, Any] | None:
    return None if row is None else row.model_dump(mode="json")


@dataclass(frozen=True, slots=True)
class Actor:
    """Who changes access. `policy` is None only for the trusted CLI (decision D5)."""

    user_id: UUID | None
    via: str  # 'api' | 'cli'
    tenant: str
    policy: Policy | None

    @classmethod
    def from_policy(cls, policy: Policy) -> Self:
        return cls(policy.user_id, "api", policy.tenant, policy)

    @classmethod
    def cli(cls, tenant: str = DEFAULT_TENANT) -> Self:
        """The trusted CLI operator (D5): skips capability and D10 checks.
        Never construct this from request or agent code."""
        return cls(None, "cli", tenant, None)

    def require(self, capability: str) -> None:
        if self.policy is not None and not self.policy.has(capability):
            msg = f"This needs {capability}. Ask an atlas admin."
            raise AccessDeniedError(msg)

    def require_any(self, *capabilities: str) -> None:
        if self.policy is not None and not any(
            self.policy.has(c) for c in capabilities
        ):
            msg = f"This needs {' or '.join(capabilities)}. Ask an atlas admin."
            raise AccessDeniedError(msg)

    def require_member_admin(self, group_id: UUID) -> None:
        if self.policy is not None and not self.policy.can_manage_members(group_id):
            msg = "Only atlas admins and the group's managers can change its members."
            raise AccessDeniedError(msg)


def _change(
    actor: Actor,
    action: str,
    target: tuple[str, UUID | str],
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> RbacChange:
    object_type, object_id = target
    return RbacChange(
        actor_user_id=actor.user_id,
        via=actor.via,
        tenant=actor.tenant,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        before=before,
        after=after,
    )


def _member_out(member: GroupMember, user: User) -> MemberOut:
    return MemberOut(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        standing=member.standing,
        added_at=member.added_at,
        role=user.role,
        status=user.status,
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _grant_capability(subject_type: str) -> str:
    """Group grants are group administration; direct user grants are user admin."""
    return ADMIN_GROUPS if subject_type == SUBJECT_GROUP else ADMIN_USERS


def _validated_target(payload: GrantCreate, now: datetime) -> str:
    if payload.expires_at is not None and payload.expires_at <= now:
        msg = "The expiry must be in the future."
        raise InvalidChangeError(msg)
    if payload.subject_type == SUBJECT_USER and not payload.reason.strip():
        msg = "Direct user grants need a reason."
        raise InvalidChangeError(msg)
    if payload.target_kind == KIND_CLEARANCE:
        msg = (
            "Field clearances arrive with row and field controls; "
            "they can't be granted yet."
        )
        raise InvalidChangeError(msg)
    if payload.target_kind == KIND_CAPABILITY:
        return _capability_target(payload)
    try:
        return validate_pattern(payload.target)
    except InvalidPatternError as exc:
        raise InvalidChangeError(str(exc)) from None


def _capability_target(payload: GrantCreate) -> str:
    if payload.subject_type != SUBJECT_USER:
        msg = (
            "Groups grant data, not actions. Change the user's role, or give the "
            "capability to a user directly."
        )
        raise InvalidChangeError(msg)
    if payload.target not in CAPABILITIES:
        msg = f"Unknown capability '{payload.target}'."
        raise InvalidChangeError(msg)
    return payload.target


def _not_self(actor: Actor, user: User) -> None:
    if actor.user_id is not None and actor.user_id == user.id:
        msg = "You can't change your own role or status. Ask another admin."
        raise ConflictError(msg)


def _no_self_membership(actor: Actor, user_id: UUID) -> None:
    """D10: joining, re-standing or leaving a group yourself changes your own
    access through the group, so it needs admin:groups, not manager standing."""
    if actor.user_id is not None and actor.user_id == user_id:
        actor.require(ADMIN_GROUPS)


def _check_role_escalation(actor: Actor, role: str) -> None:
    """D10: a role can only be assigned if its capabilities are within the
    actor's own; the CLI actor (policy None) is unaffected."""
    if actor.policy is None:
        return
    if not role_capabilities(role) <= actor.policy.capabilities:
        msg = "You can't assign a role with more access than your own."
        raise AccessDeniedError(msg)


def _update_action(before: dict[str, Any]) -> str:
    keys = set(before)
    if keys == {"role"}:
        return "user.role"
    if keys == {"status"}:
        return "user.status"
    return "user.update"


def _apply_user_update(
    actor: Actor, user: User, payload: UserUpdate
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Stage role/status changes on `user`; return the (before, after) diff.

    Empty dicts mean no-op: nothing in `payload` actually changed anything.
    """
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    if payload.role is not None and payload.role != user.role:
        if payload.role not in ROLES:
            msg = f"Unknown role '{payload.role}'. Roles: {', '.join(ROLES)}."
            raise InvalidChangeError(msg)
        _check_role_escalation(actor, payload.role)
        before["role"] = user.role
        user.role = payload.role
        after["role"] = payload.role
    if payload.status is not None and payload.status != user.status:
        before["status"] = user.status
        user.status = payload.status
        after["status"] = payload.status
    return before, after


class AccessAdmin:
    def __init__(
        self,
        repo: AccessRepository,
        access: AccessService,
        verifier: TokenVerifier | None = None,
    ) -> None:
        self._repo = repo
        self._access = access
        self._verifier = verifier

    # ---- groups -------------------------------------------------------------

    async def list_groups(self, actor: Actor) -> list[Group]:
        """Every tenant group for admin:groups (and the CLI); for a group
        manager without it, only the groups they manage, subgroups included
        (P5-D22). Rows keep their real parent_id."""
        policy = actor.policy
        if policy is not None and not policy.has(ADMIN_GROUPS):
            if not (policy.active and policy.managed_group_ids):
                actor.require(ADMIN_GROUPS)  # raises: the unchanged 403
            groups = await self._repo.list_groups(actor.tenant)
            return [g for g in groups if g.id in policy.managed_group_ids]
        return await self._repo.list_groups(actor.tenant)

    async def group_detail(self, actor: Actor, group_id: UUID) -> GroupDetailOut:
        """One group with its direct member and grant counts and its path of
        names from the root (admin:groups or a manager of it or an ancestor)."""
        actor.require_member_admin(group_id)
        group = await self._group(actor, group_id)
        groups = await self._repo.tenant_groups(actor.tenant)
        path: list[str] = []
        current: UUID | None = group.id
        while current is not None and current in groups and len(path) < len(groups):
            path.append(groups[current].name)
            current = groups[current].parent_id
        return GroupDetailOut(
            **GroupOut.model_validate(group).model_dump(),
            member_count=await self._repo.count_members(group.id),
            grant_count=await self._repo.count_grants(SUBJECT_GROUP, group.id),
            path=path[::-1],
        )

    async def member_candidates(
        self, actor: Actor, group_id: UUID, query: str
    ) -> list[MemberCandidateOut]:
        """Up to ten active human colleagues matching `query` who could join
        the group: never its members, service users or the actor (P5-D21)."""
        actor.require_member_admin(group_id)
        search = query.strip()
        shortest, longest = CANDIDATE_QUERY
        if not shortest <= len(search) <= longest:
            msg = f"Type {shortest} to {longest} characters of a name or email."
            raise InvalidChangeError(msg)
        group = await self._group(actor, group_id)
        users = await self._repo.member_candidates(
            actor.tenant,
            group.id,
            search,
            exclude_user_id=actor.user_id,
            limit=MAX_CANDIDATES,
        )
        return [
            MemberCandidateOut(user_id=u.id, display_name=u.display_name, email=u.email)
            for u in users
        ]

    async def create_group(self, actor: Actor, payload: GroupCreate) -> Group:
        actor.require(ADMIN_GROUPS)
        async with self._write(actor):
            await self._ensure_name_free(actor, payload.name)
            if payload.parent_id is not None:
                await self._group(actor, payload.parent_id)
            group = Group(
                name=payload.name,
                description=payload.description,
                parent_id=payload.parent_id,
                tenant=actor.tenant,
                created_by=actor.user_id,
            )
            self._repo.add(group)
            await self._commit(
                _change(
                    actor, "group.create", ("group", group.id), None, _snapshot(group)
                )
            )
        return group

    async def update_group(
        self, actor: Actor, group_id: UUID, payload: GroupUpdate
    ) -> Group:
        actor.require(ADMIN_GROUPS)
        async with self._write(actor):
            group = await self._group(actor, group_id)
            before = _snapshot(group)
            if payload.name is not None and payload.name != group.name:
                await self._ensure_name_free(actor, payload.name)
                group.name = payload.name
            if payload.description is not None:
                group.description = payload.description
            if "parent_id" in payload.model_fields_set:
                await self._check_parent(actor, group.id, payload.parent_id)
                group.parent_id = payload.parent_id
            after = _snapshot(group)
            if before == after:
                await self._repo.commit()  # release the lock; nothing changed
                return group
            self._repo.add(group)
            await self._commit(
                _change(actor, "group.update", ("group", group.id), before, after)
            )
        return group

    async def delete_group(self, actor: Actor, group_id: UUID) -> None:
        actor.require(ADMIN_GROUPS)
        async with self._write(actor):
            group = await self._group(actor, group_id)
            if await self._repo.group_in_use(group.id):
                msg = "Remove the group's subgroups, members and grants first."
                raise ConflictError(msg)
            before = _snapshot(group)
            await self._repo.delete(group)
            await self._commit(
                _change(actor, "group.delete", ("group", group.id), before, None)
            )

    # ---- members ------------------------------------------------------------

    async def list_members(self, actor: Actor, group_id: UUID) -> list[MemberOut]:
        actor.require_member_admin(group_id)
        group = await self._group(actor, group_id)
        return [_member_out(m, u) for m, u in await self._repo.list_members(group.id)]

    async def put_member(
        self, actor: Actor, group_id: UUID, user_id: UUID, standing: str
    ) -> MemberOut:
        if standing not in (STANDING_MEMBER, STANDING_MANAGER):
            msg = f"'{standing}' isn't a standing a member can have."
            raise InvalidChangeError(msg)
        actor.require_member_admin(group_id)
        _no_self_membership(actor, user_id)
        async with self._write(actor):
            out, change = await self._stage_member(actor, group_id, user_id, standing)
            if change is None:
                await self._repo.commit()  # release the lock; nothing changed
                return out
            await self._commit(change)
        return out

    async def _stage_member(
        self, actor: Actor, group_id: UUID, user_id: UUID, standing: str
    ) -> tuple[MemberOut, RbacChange | None]:
        """Stage a member put under the caller's `_write`; None means no-op."""
        if standing not in (STANDING_MEMBER, STANDING_MANAGER):
            msg = f"'{standing}' isn't a standing a member can have."
            raise InvalidChangeError(msg)
        actor.require_member_admin(group_id)
        _no_self_membership(actor, user_id)
        group = await self._group(actor, group_id)
        user = await self._user(actor, user_id)
        if user.kind == UserKind.SERVICE:
            # A service identity (the shared MCP user) gains whatever its
            # groups hold, for every caller of that door: admin:groups only.
            actor.require(ADMIN_GROUPS)
        member = await self._repo.member(group.id, user.id)
        # Only admin:groups appoints a manager, demotes one or edits one's
        # standing further (decision D8): a manager may only ever change
        # the membership of a plain member.
        if standing == STANDING_MANAGER or (
            member is not None and member.standing == STANDING_MANAGER
        ):
            actor.require(ADMIN_GROUPS)
        before = _snapshot(member)
        if member is None:
            member = GroupMember(
                group_id=group.id,
                user_id=user.id,
                standing=standing,
                added_by=actor.user_id,
            )
        else:
            member.standing = standing
        after = _snapshot(member)
        if before == after:
            return _member_out(member, user), None
        self._repo.add(member)
        target = ("group_member", f"{group.id}:{user.id}")
        change = _change(actor, "member.put", target, before, after)
        return _member_out(member, user), change

    async def remove_member(self, actor: Actor, group_id: UUID, user_id: UUID) -> None:
        actor.require_member_admin(group_id)
        _no_self_membership(actor, user_id)
        async with self._write(actor):
            group = await self._group(actor, group_id)
            member = await self._repo.member(group.id, user_id)
            if member is None:
                msg = "That user isn't in this group."
                raise NotFoundError(msg)
            if member.standing == STANDING_MANAGER:
                actor.require(ADMIN_GROUPS)
            if await self._carries_restriction(actor, group.id):
                # Membership carries the group's and its ancestors' grants;
                # removal lifts their denies, which widens access (D10).
                actor.require(ADMIN_GROUPS)
            before = _snapshot(member)
            await self._repo.delete(member)
            target = ("group_member", f"{group.id}:{user_id}")
            await self._commit(_change(actor, "member.remove", target, before, None))

    # ---- grants ---------------------------------------------------------

    async def list_grants(
        self, actor: Actor, subject_type: Literal["group", "user"], subject_id: UUID
    ) -> list[Grant]:
        actor.require(_grant_capability(subject_type))
        await self._subject(actor, subject_type, subject_id)
        return await self._repo.list_grants(subject_type, subject_id)

    async def create_grant(self, actor: Actor, payload: GrantCreate) -> Grant:
        actor.require(_grant_capability(payload.subject_type))
        if payload.subject_type == SUBJECT_USER and actor.user_id == payload.subject_id:
            # D10: no self-grants; only capabilities you hold.
            msg = "You can't grant access to yourself. Ask another admin."
            raise AccessDeniedError(msg)
        now = _utcnow()
        target = _validated_target(payload, now)
        if payload.target_kind == KIND_CAPABILITY:
            # D10: no self-grants; only capabilities you hold.
            actor.require(target)
        async with self._write(actor):
            grant, change = await self._stage_grant(actor, payload, now)
            await self._commit(change)
        return grant

    async def _stage_grant(
        self, actor: Actor, payload: GrantCreate, now: datetime
    ) -> tuple[Grant, RbacChange]:
        """Stage a new grant under the caller's `_write`; a duplicate is a 409."""
        actor.require(_grant_capability(payload.subject_type))
        if payload.subject_type == SUBJECT_USER and actor.user_id == payload.subject_id:
            # D10: no self-grants; only capabilities you hold.
            msg = "You can't grant access to yourself. Ask another admin."
            raise AccessDeniedError(msg)
        target = _validated_target(payload, now)
        if payload.target_kind == KIND_CAPABILITY:
            # D10: no self-grants; only capabilities you hold.
            actor.require(target)
        await self._subject(actor, payload.subject_type, payload.subject_id)
        subject = (payload.subject_type, payload.subject_id)
        existing = await self._repo.find_grant(
            subject, payload.effect, payload.target_kind, target
        )
        if existing is not None:
            expiry = as_utc(existing.expires_at)
            if expiry is not None and expiry <= now:
                msg = (
                    f"An expired grant {existing.id} for that target exists; "
                    "revoke it first."
                )
                raise ConflictError(msg)
            msg = "That grant already exists."
            raise ConflictError(msg)
        grant = Grant(
            subject_type=payload.subject_type,
            subject_id=payload.subject_id,
            effect=payload.effect,
            target_kind=payload.target_kind,
            target=target,
            reason=payload.reason.strip(),
            expires_at=payload.expires_at,
            created_by=actor.user_id,
        )
        self._repo.add(grant)
        change = _change(
            actor, "grant.create", ("grant", grant.id), None, _snapshot(grant)
        )
        return grant, change

    async def revoke_grant(self, actor: Actor, grant_id: UUID) -> None:
        actor.require_any(ADMIN_GROUPS, ADMIN_USERS)
        async with self._write(actor):
            grant = await self._repo.grant(grant_id)
            if grant is None:
                msg = "No such grant."
                raise NotFoundError(msg)
            try:
                await self._subject(actor, grant.subject_type, grant.subject_id)
            except NotFoundError:
                # Hide whether a grant exists for a subject outside the actor's
                # tenant: the same "No such grant" as an unknown id. Checked
                # before D10 below, so a cross-tenant grant always reads as
                # "No such grant", never as a D10 access-denied message.
                msg = "No such grant."
                raise NotFoundError(msg) from None
            if (
                grant.effect == EFFECT_DENY
                and grant.subject_type == SUBJECT_USER
                and grant.subject_id == actor.user_id
            ):
                # D10: revoking a deny widens access, same as a self-grant.
                msg = "You can't lift a restriction on yourself. Ask another admin."
                raise AccessDeniedError(msg)
            if grant.effect == EFFECT_DENY and grant.target_kind == KIND_CAPABILITY:
                # D10: revoking a deny widens access; only lift one you hold.
                actor.require(grant.target)
            actor.require(_grant_capability(grant.subject_type))
            before = _snapshot(grant)
            await self._repo.delete(grant)
            await self._commit(
                _change(actor, "grant.revoke", ("grant", grant.id), before, None)
            )

    # ---- users ----------------------------------------------------------

    async def list_users(self, actor: Actor, query: UserQuery) -> Page[UserOut]:
        """The tenant's users by email (keyset on (email, id)), filtered."""
        actor.require(ADMIN_USERS)
        rows = await self._repo.list_users(
            actor.tenant, query, _email_position(query.cursor)
        )
        page = rows[: query.limit]
        next_cursor = None
        if len(rows) > query.limit:
            next_cursor = encode_cursor(page[-1].email, page[-1].id)
        return Page[UserOut](
            items=[UserOut.model_validate(u) for u in page], next_cursor=next_cursor
        )

    async def user_detail(self, actor: Actor, user_id: UUID) -> UserDetailOut:
        """One user with their direct groups, direct grants and pending requests."""
        actor.require(ADMIN_USERS)  # before any lookup: no probing for user ids
        user = await self._user(actor, user_id)
        groups = await self._repo.tenant_groups(actor.tenant)
        memberships = [
            UserGroupOut(id=gid, name=groups[gid].name, standing=standing)
            for gid, standing in (await self._repo.memberships(user.id)).items()
            if gid in groups
        ]
        grants = await self._repo.list_grants(SUBJECT_USER, user.id)
        return UserDetailOut(
            **UserOut.model_validate(user).model_dump(),
            groups=sorted(memberships, key=lambda g: (g.name, g.id)),
            direct_grants=[GrantOut.model_validate(g) for g in grants],
            pending_requests=await self._repo.count_pending(user.id),
        )

    async def update_user(
        self, actor: Actor, user_id: UUID, payload: UserUpdate
    ) -> User:
        actor.require(ADMIN_USERS)  # before any lookup: no probing for user ids
        if payload.role is None and payload.status is None:
            msg = "Nothing to change: send a role or a status."
            raise InvalidChangeError(msg)
        async with self._write(actor):
            user, change = await self._stage_user_update(actor, user_id, payload)
            if change is None:
                await self._repo.commit()  # release the lock; nothing changed
                return user
            after = change.after or {}
            await self._commit(change)
        if after.get("status") == UserStatus.DISABLED:
            await self._end_firebase_sessions(user)
        return user

    async def _stage_user_update(
        self, actor: Actor, user_id: UUID, payload: UserUpdate
    ) -> tuple[User, RbacChange | None]:
        """Stage a role/status change under the caller's `_write`; None is no-op."""
        actor.require(ADMIN_USERS)
        user = await self._user(actor, user_id)
        _not_self(actor, user)
        await self._check_not_above_actor(actor, user)
        before, after = _apply_user_update(actor, user, payload)
        if not before:
            return user, None
        self._repo.add(user)
        change = _change(
            actor, _update_action(before), ("user", user.id), before, after
        )
        return user, change

    async def effective_access(self, actor: Actor, user_id: UUID) -> Policy:
        """The user's evaluated Policy, for the preview (spec §10)."""
        actor.require(ADMIN_USERS)
        user = await self._user(actor, user_id)
        return await self._access.policy_for_user(user.id)

    async def list_changes(
        self, actor: Actor, query: ChangeQuery = _ALL_CHANGES
    ) -> Page[ChangeOut]:
        """The tenant's access-change log, newest first (keyset on (at, id))."""
        actor.require(ADMIN_AUDIT)
        rows = await self._repo.list_changes(
            actor.tenant, query, page_position(query.cursor)
        )
        page, next_cursor = time_page(rows, query.limit, lambda r: (r[0].at, r[0].id))
        items = [
            ChangeOut.model_validate({**change.model_dump(), "actor": _actor_ref(user)})
            for change, user in page
        ]
        return Page[ChangeOut](items=items, next_cursor=next_cursor)

    async def list_decisions(
        self, actor: Actor, query: DecisionQuery = _ALL_DECISIONS
    ) -> Page[AuditDecisionOut]:
        """The tenant's atlas tool decisions, newest first (keyset on
        (created_at, id)); rows with no user are never listed."""
        actor.require(ADMIN_AUDIT)
        rows = await self._repo.list_decisions(
            actor.tenant, query, page_position(query.cursor)
        )
        page, next_cursor = time_page(
            rows, query.limit, lambda r: (r[0].created_at, r[0].id)
        )
        items = [_decision_out(entry, user) for entry, user in page]
        return Page[AuditDecisionOut](items=items, next_cursor=next_cursor)

    async def audit_summary(
        self, actor: Actor, days: Literal[7, 30]
    ) -> AuditSummaryOut:
        """Allow/deny per UTC day over the last `days` days (today included,
        zero-filled), plus the top deny reasons and the most-denied users."""
        actor.require(ADMIN_AUDIT)
        today = _utcnow().date()
        first = today - timedelta(days=days - 1)
        since = datetime.combine(first, time.min, tzinfo=UTC)
        counts = {
            (day, decision): n
            for day, decision, n in await self._repo.decision_counts_by_day(
                actor.tenant, since
            )
        }
        per_day = [
            DayCountOut(
                date=day,
                allow=counts.get((day, "allow"), 0),
                deny=counts.get((day, "deny"), 0),
            )
            for day in (first + timedelta(days=i) for i in range(days))
        ]
        reasons = await self._repo.top_deny_reasons(actor.tenant, since, _TOP)
        users = await self._repo.top_denied_users(actor.tenant, since, _TOP)
        return AuditSummaryOut(
            days=days,
            per_day=per_day,
            top_deny_reasons=[
                ReasonCountOut(reason=reason or _NO_REASON, count=n)
                for reason, n in reasons
            ],
            top_denied_users=[
                UserCountOut(user_id=uid, display_name=name, count=n)
                for uid, name, n in users
            ],
        )

    async def _check_not_above_actor(self, actor: Actor, user: User) -> None:
        """D10: nobody changes the role or status of a user whose effective
        capabilities exceed their own (the CLI actor, policy None, is unaffected).

        Judged by the capabilities the target would have if active: a disabled
        user's real Policy is deny_all with empty capabilities, which would
        otherwise let anyone with admin:users re-enable or re-role them.
        """
        if actor.policy is None:
            return
        target_capabilities = await self._access.capabilities_if_active(user.id)
        if not target_capabilities <= actor.policy.capabilities:
            msg = "You can't change a user with more access than your own."
            raise AccessDeniedError(msg)

    async def _end_firebase_sessions(self, user: User) -> None:
        if self._verifier is None or not user.firebase_uid:
            return
        try:
            await self._verifier.revoke(user.firebase_uid)
        except Exception:
            # Status is enforced on every request; revocation only ends sessions sooner.
            logger.exception("access.revoke_failed", user_id=str(user.id))
        else:
            logger.info("access.sessions_revoked", user_id=str(user.id))

    # ---- helpers ------------------------------------------------------------

    @asynccontextmanager
    async def _write(self, actor: Actor) -> AsyncGenerator[None]:
        """One admin write: take the write lock, re-check the actor's
        authority under it, then run the body.

        Authority checks run against the policy resolved at request start. If
        any access change committed since (the actor may have been disabled or
        demoted meanwhile), the write is refused with a 409 rather than judged
        on stale authority. The trusted CLI actor (D5) has no policy to go
        stale. No-op writes take the same path, so they are refused too: a
        harmless retry, and one rule with no exceptions.

        Keeps the session usable after any failed write (CLI runs several
        commands per session). A constraint violation caught only at commit
        time (two writers racing past an application-level check) becomes a
        409; anything else rolls back and re-raises as-is.
        """
        try:
            version = await self._repo.lock_for_write()
            if actor.policy is not None and version != actor.policy.policy_version:
                logger.info(
                    "access.stale_actor",
                    actor_user_id=str(actor.user_id),
                    resolved_version=actor.policy.policy_version,
                    current_version=version,
                )
                msg = "Access changed while this request was running; retry."
                raise ConflictError(msg)
            yield
        except IntegrityError:
            await self._repo.rollback()
            msg = "That change conflicts with another change; reload and try again."
            raise ConflictError(msg) from None
        except Exception:
            await self._repo.rollback()
            raise

    async def _commit(self, *changes: RbacChange) -> None:
        """Stage every row, bump policy_version ONCE, commit, log each action."""
        for change in changes:
            self._repo.add(change)
        await self._repo.bump_version()
        await self._repo.commit()
        for change in changes:
            logger.info(
                "access.changed",
                action=change.action,
                object_id=change.object_id,
                via=change.via,
            )

    async def _group(self, actor: Actor, group_id: UUID) -> Group:
        group = await self._repo.group(group_id)
        if group is None or group.tenant != actor.tenant:
            msg = "No such group."
            raise NotFoundError(msg)
        return group

    async def _user(self, actor: Actor, user_id: UUID) -> User:
        user = await self._repo.user(user_id)
        if user is None or user.tenant != actor.tenant:
            msg = "No such user."
            raise NotFoundError(msg)
        return user

    async def _subject(self, actor: Actor, subject_type: str, subject_id: UUID) -> None:
        """The grant subject must exist in the actor's tenant."""
        if subject_type == SUBJECT_GROUP:
            await self._group(actor, subject_id)
        else:
            await self._user(actor, subject_id)

    async def _carries_restriction(self, actor: Actor, group_id: UUID) -> bool:
        """True when the group or any ancestor holds a live deny (or a
        malformed grant), judged as the evaluator judges it."""
        groups = await self._repo.tenant_groups(actor.tenant)
        lineage = with_ancestors((group_id,), groups)
        now = _utcnow()
        return any(restricts(g, now) for g in await self._repo.group_grants(lineage))

    async def _ensure_name_free(self, actor: Actor, name: str) -> None:
        if await self._repo.group_by_name(actor.tenant, name) is not None:
            msg = f"A group named '{name}' already exists."
            raise ConflictError(msg)

    async def _check_parent(
        self, actor: Actor, group_id: UUID, parent_id: UUID | None
    ) -> None:
        """Reject a parent that is the group itself or one of its subgroups."""
        if parent_id is None:
            return
        groups = await self._repo.tenant_groups(actor.tenant)
        if parent_id not in groups:
            msg = "No such parent group."
            raise NotFoundError(msg)
        current: UUID | None = parent_id
        seen: set[UUID] = set()
        while current is not None and current in groups and current not in seen:
            if current == group_id:
                msg = "A group can't sit under itself or one of its subgroups."
                raise InvalidChangeError(msg)
            seen.add(current)
            current = groups[current].parent_id

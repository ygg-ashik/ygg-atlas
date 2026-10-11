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

import re
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
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
    CLEARANCES,
    ROLES,
    role_capabilities,
)
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.evaluator import restricts, with_ancestors
from app.access.facts import (
    BUILTIN_ATTRIBUTES,
    DEFAULT_TENANT,
    EFFECT_ALLOW,
    EFFECT_DENY,
    KIND_CAPABILITY,
    KIND_CLEARANCE,
    KIND_RESOURCE,
    MASK_MODES,
    MASKABLE_LABEL_CLASSES,
    MAX_ATTRIBUTE_VALUE,
    MAX_BUCKET_SIZE,
    SELF_TOKEN,
    STANDING_MANAGER,
    STANDING_MEMBER,
    SUBJECT_GROUP,
    SUBJECT_USER,
    as_utc,
    is_well_formed_scope,
)
from app.access.models import (
    Grant,
    Group,
    GroupMember,
    LabelClassSetting,
    RbacChange,
    ScopeDimension,
    UserAttribute,
)
from app.access.patterns import (
    MAX_SEGMENTS,
    InvalidPatternError,
    matches,
    validate_pattern,
)
from app.access.policy import Policy
from app.access.repository import AccessRepository
from app.access.schemas import (
    GrantCreate,
    GroupCreate,
    GroupUpdate,
    MemberOut,
    UserUpdate,
)
from app.access.service import AccessService
from app.identity import (
    REVOKED_USER_DISABLED,
    TokenVerifier,
    User,
    UserKind,
    UserStatus,
    revoke_user_tokens,
    service_account_email,
)

logger = structlog.get_logger()


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
        return _clearance_target(payload)
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


def _clearance_target(payload: GrantCreate) -> str:
    """A field clearance (spec §5.6): a known code, for a group or a user."""
    if payload.target not in CLEARANCES:
        msg = (
            f"Unknown clearance '{payload.target}'. "
            f"Clearances: {', '.join(CLEARANCES)}."
        )
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


_ATTRIBUTE_KEY: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MASK_SUPPRESS: Final = "suppress"  # the mode with no stored row (C17)


def _check_scope_shape(payload: GrantCreate) -> None:
    """Row scopes ride on resource allows only (spec §15), and never in a
    shape the evaluator would treat as malformed (D3.3): storing one would
    deny everything to everyone the grant applies to."""
    if payload.row_scope is None:
        return
    if payload.effect != EFFECT_ALLOW:
        msg = (
            "A deny can't carry a row scope: deny the whole resource, or "
            "narrow an allow instead."
        )
        raise InvalidChangeError(msg)
    if payload.target_kind != KIND_RESOURCE:
        msg = "Only data grants can carry a row scope."
        raise InvalidChangeError(msg)
    if not is_well_formed_scope(payload.row_scope):
        msg = "That row scope is not valid."
        raise InvalidChangeError(msg)


def _require_clearance(actor: Actor, clearance: str) -> None:
    """C10 (the D10 analogue): granting a clearance, or lifting a clearance
    deny, widens access, so an API actor must hold that clearance; the
    trusted CLI (policy None) is exempt."""
    if actor.policy is not None and not actor.policy.has_clearance(clearance):
        msg = (
            f"You can only grant or lift the '{clearance}' clearance if you "
            "hold it yourself."
        )
        raise AccessDeniedError(msg)


def _covers_entity(pattern: str, source: str, entity: str) -> bool:
    """True if `pattern` reaches anything in `source/entity`; an item pattern
    (`demo/order/revenue`, `demo/*/revenue`) is judged by its entity part."""
    segments = pattern.split("/")
    if len(segments) == MAX_SEGMENTS:
        pattern = "/".join(segments[:2])
    return matches(pattern, f"{source}/{entity}")


def _check_attribute_key(key: str) -> None:
    if key in BUILTIN_ATTRIBUTES:
        msg = (
            f"'{key}' is built in: it always comes from the user's account "
            "and can't be set."
        )
        raise InvalidChangeError(msg)
    if not _ATTRIBUTE_KEY.fullmatch(key):
        msg = (
            f"'{key}' is not an attribute key: use up to 64 lowercase letters, "
            "digits and underscores, starting with a letter."
        )
        raise InvalidChangeError(msg)


def _is_live(expires_at: datetime | None, now: datetime) -> bool:
    expiry = as_utc(expires_at)
    return expiry is None or expiry > now


def _not_self_attribute(actor: Actor, user: User) -> None:
    """Attributes feed `$self` row scopes, so they are permissions (D3.5)."""
    if actor.user_id is not None and actor.user_id == user.id:
        msg = "You can't change your own attributes. Ask another admin."
        raise ConflictError(msg)


def _attribute_snapshot(row: UserAttribute | None) -> dict[str, Any] | None:
    return None if row is None else {"key": row.key, "value": row.value}


def _check_label_class(label_class: str, mode: str, bucket_size: int | None) -> None:
    if label_class not in MASKABLE_LABEL_CLASSES:
        msg = (
            f"'{label_class}' labels can't be set: only "
            f"{' and '.join(MASKABLE_LABEL_CLASSES)} are masked."
        )
        raise InvalidChangeError(msg)
    if mode not in MASK_MODES:
        msg = f"'{mode}' is not a mask mode. Modes: {', '.join(MASK_MODES)}."
        raise InvalidChangeError(msg)
    if bucket_size is not None and not 1 <= bucket_size <= MAX_BUCKET_SIZE:
        msg = f"The bucket size must be between 1 and {MAX_BUCKET_SIZE}."
        raise InvalidChangeError(msg)


def _label_class_snapshot(row: LabelClassSetting | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "label_class": row.label_class,
        "mode": row.mode,
        "bucket_size": row.bucket_size,
    }


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
        actor.require(ADMIN_GROUPS)
        return await self._repo.list_groups(actor.tenant)

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
                if payload.parent_id != group.parent_id:
                    await self._check_move_clearances(
                        actor, group.parent_id, payload.parent_id
                    )
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
            if member is None:
                # Joining inherits the lineage's clearance allows (C10).
                lineage = await self._lineage(actor, group.id)
                await self._require_clearances(actor, lineage, EFFECT_ALLOW)
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
                await self._repo.commit()  # release the lock; nothing changed
                return _member_out(member, user)
            self._repo.add(member)
            target = ("group_member", f"{group.id}:{user.id}")
            await self._commit(_change(actor, "member.put", target, before, after))
        return _member_out(member, user)

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
            # Leaving lifts the lineage's clearance denies (C10).
            lineage = await self._lineage(actor, group.id)
            await self._require_clearances(actor, lineage, EFFECT_DENY)
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
        _check_scope_shape(payload)
        if payload.target_kind == KIND_CAPABILITY:
            # D10: no self-grants; only capabilities you hold.
            actor.require(target)
        if payload.target_kind == KIND_CLEARANCE and payload.effect == EFFECT_ALLOW:
            _require_clearance(actor, target)  # C10
        async with self._write(actor):
            await self._subject(actor, payload.subject_type, payload.subject_id)
            if payload.row_scope is not None:
                await self._check_scope(target, payload.row_scope)
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
                row_scope=payload.row_scope,
            )
            self._repo.add(grant)
            await self._commit(
                _change(
                    actor, "grant.create", ("grant", grant.id), None, _snapshot(grant)
                )
            )
        return grant

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
            if grant.effect == EFFECT_DENY and grant.target_kind == KIND_CLEARANCE:
                _require_clearance(actor, grant.target)  # C10
            actor.require(_grant_capability(grant.subject_type))
            before = _snapshot(grant)
            await self._repo.delete(grant)
            await self._commit(
                _change(actor, "grant.revoke", ("grant", grant.id), before, None)
            )

    # ---- users ----------------------------------------------------------

    async def list_users(
        self, actor: Actor, query: str = "", limit: int = 50
    ) -> list[User]:
        actor.require(ADMIN_USERS)
        return await self._repo.list_users(actor.tenant, query.strip(), limit)

    async def update_user(
        self, actor: Actor, user_id: UUID, payload: UserUpdate
    ) -> User:
        actor.require(ADMIN_USERS)  # before any lookup: no probing for user ids
        if payload.role is None and payload.status is None:
            msg = "Nothing to change: send a role or a status."
            raise InvalidChangeError(msg)
        async with self._write(actor):
            user = await self._user(actor, user_id)
            _not_self(actor, user)
            await self._check_not_above_actor(actor, user)
            before, after = _apply_user_update(actor, user, payload)
            if not before:
                await self._repo.commit()  # release the lock; nothing changed
                return user
            self._repo.add(user)
            await self._commit(
                _change(actor, _update_action(before), ("user", user.id), before, after)
            )
        if after.get("status") == UserStatus.DISABLED:
            await self._end_firebase_sessions(user)
            await revoke_user_tokens(
                user.id,
                reason=REVOKED_USER_DISABLED,
                actor_user_id=actor.user_id,
                via="cli" if actor.via == "cli" else "api",
            )
        return user

    async def effective_access(self, actor: Actor, user_id: UUID) -> Policy:
        """The user's evaluated Policy, for the preview (spec §10)."""
        actor.require(ADMIN_USERS)
        user = await self._user(actor, user_id)
        return await self._access.policy_for_user(user.id)

    async def list_changes(self, actor: Actor, limit: int = 100) -> list[RbacChange]:
        actor.require(ADMIN_AUDIT)
        return await self._repo.list_changes(actor.tenant, limit)

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

    # ---- user attributes (D3.5) -----------------------------------------

    async def list_attributes(self, actor: Actor, user_id: UUID) -> list[UserAttribute]:
        actor.require(ADMIN_USERS)
        user = await self._user(actor, user_id)
        return await self._repo.list_attributes(user.id)

    async def set_attribute(
        self, actor: Actor, user_id: UUID, key: str, value: str
    ) -> UserAttribute:
        """Set one attribute; `$self` in a row scope resolves to it."""
        actor.require(ADMIN_USERS)  # before any lookup: no probing for user ids
        _check_attribute_key(key)
        value = value.strip()
        if not 1 <= len(value) <= MAX_ATTRIBUTE_VALUE:
            msg = f"An attribute value is 1 to {MAX_ATTRIBUTE_VALUE} characters."
            raise InvalidChangeError(msg)
        async with self._write(actor):
            user = await self._user(actor, user_id)
            _not_self_attribute(actor, user)
            row = await self._repo.attribute(user.id, key)
            before = _attribute_snapshot(row)
            if row is not None and row.value == value:
                await self._repo.commit()  # release the lock; nothing changed
                return row
            if row is None:
                row = UserAttribute(user_id=user.id, key=key, value=value)
            row.value = value
            row.set_by = actor.user_id
            row.set_at = _utcnow()
            self._repo.add(row)
            await self._commit(
                _change(
                    actor,
                    "attribute.set",
                    ("user_attribute", f"{user.id}:{key}"),
                    before,
                    _attribute_snapshot(row),
                )
            )
        return row

    async def delete_attribute(self, actor: Actor, user_id: UUID, key: str) -> None:
        actor.require(ADMIN_USERS)
        _check_attribute_key(key)
        async with self._write(actor):
            user = await self._user(actor, user_id)
            _not_self_attribute(actor, user)
            row = await self._repo.attribute(user.id, key)
            if row is None:
                msg = f"That user has no attribute '{key}'."
                raise NotFoundError(msg)
            before = _attribute_snapshot(row)
            await self._repo.delete(row)
            await self._commit(
                _change(
                    actor,
                    "attribute.delete",
                    ("user_attribute", f"{user.id}:{key}"),
                    before,
                    None,
                )
            )

    # ---- label classes (D3.9) ---------------------------------------------

    async def list_label_classes(self, actor: Actor) -> list[LabelClassSetting]:
        """Both maskable classes (C12); an unset one shows as `suppress`, which
        is what the atlas does without a row (fail closed)."""
        actor.require(ADMIN_GROUPS)
        stored = {row.label_class: row for row in await self._repo.list_label_classes()}
        return [
            stored.get(name) or LabelClassSetting(label_class=name, mode=_MASK_SUPPRESS)
            for name in MASKABLE_LABEL_CLASSES
        ]

    async def set_label_class(
        self,
        actor: Actor,
        label_class: str,
        mode: str,
        bucket_size: int | None = None,
    ) -> LabelClassSetting:
        """How a label class shows to callers without its clearance.
        An omitted `bucket_size` keeps the stored one."""
        actor.require(ADMIN_GROUPS)
        _check_label_class(label_class, mode, bucket_size)
        async with self._write(actor):
            row = await self._repo.label_class(label_class)
            before = _label_class_snapshot(row)
            if row is None:
                row = LabelClassSetting(label_class=label_class, mode=mode)
            row.mode = mode
            if bucket_size is not None:
                row.bucket_size = bucket_size
            after = _label_class_snapshot(row)
            if before == after:
                await self._repo.commit()  # release the lock; nothing changed
                return row
            row.updated_at = _utcnow()
            self._repo.add(row)
            await self._commit(
                _change(
                    actor,
                    "label_class.update",
                    ("label_class", label_class),
                    before,
                    after,
                )
            )
        return row

    # ---- scope dimensions (D3.6) ------------------------------------------

    async def list_scope_dimensions(self, actor: Actor) -> list[ScopeDimension]:
        """The dimensions enabled plugins declare, for building scoped grants."""
        actor.require_any(ADMIN_GROUPS, ADMIN_USERS)
        return await self._repo.scope_dimensions()

    async def _check_scope(
        self, pattern: str, scope: Mapping[str, Sequence[str]]
    ) -> None:
        """D3.6: every dimension is declared by at least one entity the pattern
        covers (for a one-entity pattern: by that entity), and `$self` only on
        a dimension that declares it. The mirror holds enabled plugins only, so
        a scope on a disabled plugin's data is rejected (fail closed)."""
        declared = {
            row.dimension
            for row in await self._repo.scope_dimensions()
            if _covers_entity(pattern, row.source, row.entity)
        }
        if not declared:
            msg = (
                f"Nothing under '{pattern}' can be row-scoped: its data declares "
                "no scope dimensions, or its data source isn't enabled."
            )
            raise InvalidChangeError(msg)
        unknown = sorted(set(scope) - declared)
        if unknown:
            msg = (
                f"The data under '{pattern}' can't be scoped by "
                f"{', '.join(unknown)}. It can be scoped by "
                f"{', '.join(sorted(declared))}."
            )
            raise InvalidChangeError(msg)
        self_attributes = await self._repo.self_attributes()
        for dimension in sorted(scope):
            if SELF_TOKEN in scope[dimension] and dimension not in self_attributes:
                msg = (
                    f"'{dimension}' has no {SELF_TOKEN}: list the values to "
                    "match instead."
                )
                raise InvalidChangeError(msg)

    async def _lineage(self, actor: Actor, group_id: UUID | None) -> frozenset[UUID]:
        if group_id is None:
            return frozenset()
        groups = await self._repo.tenant_groups(actor.tenant)
        return with_ancestors((group_id,), groups)

    async def _check_move_clearances(
        self, actor: Actor, old_parent: UUID | None, new_parent: UUID | None
    ) -> None:
        """Re-parenting a group gains the new ancestors' clearance allows and
        lifts the old ancestors' clearance denies for all its members (C10)."""
        old = await self._lineage(actor, old_parent)
        new = await self._lineage(actor, new_parent)
        await self._require_clearances(actor, new - old, EFFECT_ALLOW)
        await self._require_clearances(actor, old - new, EFFECT_DENY)

    async def _require_clearances(
        self, actor: Actor, group_ids: frozenset[UUID], effect: str
    ) -> None:
        """`_require_clearance` for every live clearance grant with `effect`
        on `group_ids`; the CLI (no policy) is exempt."""
        if actor.policy is None or not group_ids:
            return
        now = _utcnow()
        codes = {
            grant.target
            for grant in await self._repo.group_grants(group_ids)
            if grant.target_kind == KIND_CLEARANCE
            and grant.effect == effect
            and _is_live(grant.expires_at, now)
        }
        for code in sorted(codes):
            _require_clearance(actor, code)

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

    async def _commit(self, change: RbacChange) -> None:
        self._repo.add(change)
        await self._repo.bump_version()
        await self._repo.commit()
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

    async def create_service_account(self, actor: Actor, name: str, role: str) -> User:
        """D13: a service identity owned by the actor; audited and versioned."""
        actor.require(ADMIN_USERS)
        if role not in ROLES:
            msg = f"Unknown role '{role}'. Roles: {', '.join(ROLES)}."
            raise InvalidChangeError(msg)
        _check_role_escalation(actor, role)
        email = service_account_email(name)
        if email is None:
            msg = "Use 3-40 letters, digits or dashes for the service account name."
            raise InvalidChangeError(msg)
        async with self._write(actor):
            if await self._repo.user_by_email(email) is not None:
                msg = f"A service account '{email}' already exists."
                raise ConflictError(msg)
            user = User(
                email=email,
                display_name=name.strip(),
                kind=UserKind.SERVICE,
                role=role,
                owner_user_id=actor.user_id,
                tenant=actor.tenant,
            )
            self._repo.add(user)
            await self._commit(
                _change(
                    actor,
                    "service_account.create",
                    ("user", user.id),
                    None,
                    _snapshot(user),
                )
            )
        return user

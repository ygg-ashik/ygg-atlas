"""Administration of access (spec §5, §10): groups, members, grants, roles, status.

Each write is one unit of work: the change, its rbac_changes row and the
policy_version bump commit together, so no cached policy can miss a change.
"""

from dataclasses import dataclass
from typing import Any, Self
from uuid import UUID

import structlog
from sqlmodel import SQLModel

from app.access.catalog import ADMIN_GROUPS
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.facts import DEFAULT_TENANT, STANDING_MANAGER
from app.access.models import Group, GroupMember, RbacChange
from app.access.policy import Policy
from app.access.repository import AccessRepository
from app.access.schemas import GroupCreate, GroupUpdate, MemberOut
from app.access.service import AccessService
from app.identity import TokenVerifier, User

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
        return cls(None, "cli", tenant, None)

    def require(self, capability: str) -> None:
        if self.policy is not None and not self.policy.has(capability):
            msg = f"This needs {capability}. Ask an atlas admin."
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
            _change(actor, "group.create", ("group", group.id), None, _snapshot(group))
        )
        return group

    async def update_group(
        self, actor: Actor, group_id: UUID, payload: GroupUpdate
    ) -> Group:
        actor.require(ADMIN_GROUPS)
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
        self._repo.add(group)
        await self._commit(
            _change(
                actor, "group.update", ("group", group.id), before, _snapshot(group)
            )
        )
        return group

    async def delete_group(self, actor: Actor, group_id: UUID) -> None:
        actor.require(ADMIN_GROUPS)
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
        group = await self._group(actor, group_id)
        actor.require_member_admin(group.id)
        return [_member_out(m, u) for m, u in await self._repo.list_members(group.id)]

    async def put_member(
        self, actor: Actor, group_id: UUID, user_id: UUID, standing: str
    ) -> MemberOut:
        group = await self._group(actor, group_id)
        actor.require_member_admin(group.id)
        if standing == STANDING_MANAGER:
            actor.require(ADMIN_GROUPS)  # decision D8
        user = await self._user(actor, user_id)
        member = await self._repo.member(group.id, user.id)
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
        self._repo.add(member)
        target = ("group_member", f"{group.id}:{user.id}")
        await self._commit(
            _change(actor, "member.put", target, before, _snapshot(member))
        )
        return _member_out(member, user)

    async def remove_member(self, actor: Actor, group_id: UUID, user_id: UUID) -> None:
        group = await self._group(actor, group_id)
        actor.require_member_admin(group.id)
        member = await self._repo.member(group.id, user_id)
        if member is None:
            msg = "That user isn't in this group."
            raise NotFoundError(msg)
        if member.standing == STANDING_MANAGER:
            actor.require(ADMIN_GROUPS)
        before = _snapshot(member)
        await self._repo.delete(member)
        target = ("group_member", f"{group.id}:{user_id}")
        await self._commit(_change(actor, "member.remove", target, before, None))

    # ---- helpers ------------------------------------------------------------

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

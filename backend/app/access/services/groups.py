"""Groups: list, detail, create, update (rename, re-parent) and delete."""

from uuid import UUID

from app.access.actor import Actor
from app.access.catalog import ADMIN_GROUPS
from app.access.errors import ConflictError, InvalidChangeError, NotFoundError
from app.access.facts import EFFECT_ALLOW, EFFECT_DENY, SUBJECT_GROUP
from app.access.models import Group
from app.access.repositories import AccessRepository
from app.access.schemas import GroupCreate, GroupDetailOut, GroupOut, GroupUpdate
from app.access.services.lookup import TenantLookup
from app.access.services.writer import AccessWriter, rbac_change, snapshot


class GroupService:
    """Group administration (admin:groups; managers see their own groups)."""

    def __init__(self, repo: AccessRepository, writer: AccessWriter) -> None:
        self._repo = repo
        self._writer = writer
        self._lookup = TenantLookup(repo)

    async def list_groups(self, actor: Actor) -> list[Group]:
        """Every tenant group for admin:groups (and the CLI); for a group
        manager without it, only the groups they manage, subgroups included.
        Rows keep their real parent_id."""
        policy = actor.policy
        if policy is not None and not policy.has(ADMIN_GROUPS):
            if not (policy.active and policy.managed_group_ids):
                actor.require(ADMIN_GROUPS)  # raises: the unchanged 403
            groups = await self._repo.groups.list_groups(actor.tenant)
            return [g for g in groups if g.id in policy.managed_group_ids]
        return await self._repo.groups.list_groups(actor.tenant)

    async def group_detail(self, actor: Actor, group_id: UUID) -> GroupDetailOut:
        """One group with its direct member and grant counts and its path of
        names from the root (admin:groups or a manager of it or an ancestor)."""
        actor.require_member_admin(group_id)
        group = await self._lookup.group(actor, group_id)
        groups = await self._repo.groups.tenant_groups(actor.tenant)
        path: list[str] = []
        current: UUID | None = group.id
        while current is not None and current in groups and len(path) < len(groups):
            path.append(groups[current].name)
            current = groups[current].parent_id
        return GroupDetailOut(
            **GroupOut.model_validate(group).model_dump(),
            member_count=await self._repo.groups.count_members(group.id),
            grant_count=await self._repo.grants.count_grants(SUBJECT_GROUP, group.id),
            path=path[::-1],
        )

    async def create_group(self, actor: Actor, payload: GroupCreate) -> Group:
        actor.require(ADMIN_GROUPS)
        async with self._writer.write(actor):
            await self._ensure_name_free(actor, payload.name)
            if payload.parent_id is not None:
                await self._lookup.group(actor, payload.parent_id)
            group = Group(
                name=payload.name,
                description=payload.description,
                parent_id=payload.parent_id,
                tenant=actor.tenant,
                created_by=actor.user_id,
            )
            self._repo.add(group)
            await self._writer.commit(
                rbac_change(
                    actor, "group.create", ("group", group.id), None, snapshot(group)
                )
            )
        return group

    async def update_group(
        self, actor: Actor, group_id: UUID, payload: GroupUpdate
    ) -> Group:
        actor.require(ADMIN_GROUPS)
        async with self._writer.write(actor):
            group = await self._lookup.group(actor, group_id)
            before = snapshot(group)
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
            after = snapshot(group)
            if before == after:
                await self._repo.commit()  # release the lock; nothing changed
                return group
            self._repo.add(group)
            await self._writer.commit(
                rbac_change(actor, "group.update", ("group", group.id), before, after)
            )
        return group

    async def delete_group(self, actor: Actor, group_id: UUID) -> None:
        actor.require(ADMIN_GROUPS)
        async with self._writer.write(actor):
            group = await self._lookup.group(actor, group_id)
            if await self._repo.groups.group_in_use(group.id):
                msg = "Remove the group's subgroups, members and grants first."
                raise ConflictError(msg)
            before = snapshot(group)
            await self._repo.delete(group)
            await self._writer.commit(
                rbac_change(actor, "group.delete", ("group", group.id), before, None)
            )

    async def _check_move_clearances(
        self, actor: Actor, old_parent: UUID | None, new_parent: UUID | None
    ) -> None:
        """Re-parenting a group gains the new ancestors' clearance allows and
        lifts the old ancestors' clearance denies for all its members."""
        old = await self._lookup.lineage(actor, old_parent)
        new = await self._lookup.lineage(actor, new_parent)
        await self._lookup.require_clearances(actor, new - old, EFFECT_ALLOW)
        await self._lookup.require_clearances(actor, old - new, EFFECT_DENY)

    async def _ensure_name_free(self, actor: Actor, name: str) -> None:
        if await self._repo.groups.group_by_name(actor.tenant, name) is not None:
            msg = f"A group named '{name}' already exists."
            raise ConflictError(msg)

    async def _check_parent(
        self, actor: Actor, group_id: UUID, parent_id: UUID | None
    ) -> None:
        """Reject a parent that is the group itself or one of its subgroups."""
        if parent_id is None:
            return
        groups = await self._repo.groups.tenant_groups(actor.tenant)
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

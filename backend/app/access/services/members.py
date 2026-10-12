"""Group members: list, add or re-stand, remove, and the add-member search."""

from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from app.access.actor import Actor
from app.access.catalog import ADMIN_GROUPS
from app.access.errors import InvalidChangeError, NotFoundError
from app.access.evaluator import restricts, with_ancestors
from app.access.facts import (
    EFFECT_ALLOW,
    EFFECT_DENY,
    STANDING_MANAGER,
    STANDING_MEMBER,
)
from app.access.models import GroupMember, RbacChange
from app.access.repositories import AccessRepository
from app.access.schemas import MemberCandidateOut, MemberOut
from app.access.services.lookup import TenantLookup
from app.access.services.writer import AccessWriter, rbac_change, snapshot
from app.identity import User, UserKind

MAX_CANDIDATES: Final = 10  # member-candidate lookup (P5-D21)
CANDIDATE_QUERY: Final = (3, 100)  # stripped length bounds


def _utcnow() -> datetime:
    return datetime.now(UTC)


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


def _no_self_membership(actor: Actor, user_id: UUID) -> None:
    """D10: joining, re-standing or leaving a group yourself changes your own
    access through the group, so it needs admin:groups, not manager standing."""
    if actor.user_id is not None and actor.user_id == user_id:
        actor.require(ADMIN_GROUPS)


class MemberService:
    """Membership changes, by atlas admins or the group's managers (D8, D10)."""

    def __init__(self, repo: AccessRepository, writer: AccessWriter) -> None:
        self._repo = repo
        self._writer = writer
        self._lookup = TenantLookup(repo)

    async def list_members(self, actor: Actor, group_id: UUID) -> list[MemberOut]:
        actor.require_member_admin(group_id)
        group = await self._lookup.group(actor, group_id)
        return [
            _member_out(m, u) for m, u in await self._repo.groups.list_members(group.id)
        ]

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
        group = await self._lookup.group(actor, group_id)
        users = await self._repo.users.member_candidates(
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

    async def put_member(
        self, actor: Actor, group_id: UUID, user_id: UUID, standing: str
    ) -> MemberOut:
        if standing not in (STANDING_MEMBER, STANDING_MANAGER):
            msg = f"'{standing}' isn't a standing a member can have."
            raise InvalidChangeError(msg)
        actor.require_member_admin(group_id)
        _no_self_membership(actor, user_id)
        async with self._writer.write(actor):
            out, change = await self.stage_member(actor, group_id, user_id, standing)
            if change is None:
                await self._repo.commit()  # release the lock; nothing changed
                return out
            await self._writer.commit(change)
        return out

    async def stage_member(
        self, actor: Actor, group_id: UUID, user_id: UUID, standing: str
    ) -> tuple[MemberOut, RbacChange | None]:
        """Stage a member put under the caller's `AccessWriter.write`; None
        means no-op."""
        if standing not in (STANDING_MEMBER, STANDING_MANAGER):
            msg = f"'{standing}' isn't a standing a member can have."
            raise InvalidChangeError(msg)
        actor.require_member_admin(group_id)
        _no_self_membership(actor, user_id)
        group = await self._lookup.group(actor, group_id)
        user = await self._lookup.user(actor, user_id)
        if user.kind == UserKind.SERVICE:
            # A service identity (the shared MCP user) gains whatever its
            # groups hold, for every caller of that door: admin:groups only.
            actor.require(ADMIN_GROUPS)
        member = await self._repo.groups.member(group.id, user.id)
        # Only admin:groups appoints a manager, demotes one or edits one's
        # standing further (decision D8): a manager may only ever change
        # the membership of a plain member.
        if standing == STANDING_MANAGER or (
            member is not None and member.standing == STANDING_MANAGER
        ):
            actor.require(ADMIN_GROUPS)
        if member is None:
            # Joining inherits the lineage's clearance allows (C10).
            lineage = await self._lookup.lineage(actor, group.id)
            await self._lookup.require_clearances(actor, lineage, EFFECT_ALLOW)
        before = snapshot(member)
        if member is None:
            member = GroupMember(
                group_id=group.id,
                user_id=user.id,
                standing=standing,
                added_by=actor.user_id,
            )
        else:
            member.standing = standing
        after = snapshot(member)
        if before == after:
            return _member_out(member, user), None
        self._repo.add(member)
        target = ("group_member", f"{group.id}:{user.id}")
        change = rbac_change(actor, "member.put", target, before, after)
        return _member_out(member, user), change

    async def remove_member(self, actor: Actor, group_id: UUID, user_id: UUID) -> None:
        actor.require_member_admin(group_id)
        _no_self_membership(actor, user_id)
        async with self._writer.write(actor):
            group = await self._lookup.group(actor, group_id)
            member = await self._repo.groups.member(group.id, user_id)
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
            lineage = await self._lookup.lineage(actor, group.id)
            await self._lookup.require_clearances(actor, lineage, EFFECT_DENY)
            before = snapshot(member)
            await self._repo.delete(member)
            target = ("group_member", f"{group.id}:{user_id}")
            await self._writer.commit(
                rbac_change(actor, "member.remove", target, before, None)
            )

    async def _carries_restriction(self, actor: Actor, group_id: UUID) -> bool:
        """True when the group or any ancestor holds a live deny (or a
        malformed grant), judged as the evaluator judges it."""
        groups = await self._repo.groups.tenant_groups(actor.tenant)
        lineage = with_ancestors((group_id,), groups)
        now = _utcnow()
        return any(
            restricts(g, now) for g in await self._repo.grants.group_grants(lineage)
        )

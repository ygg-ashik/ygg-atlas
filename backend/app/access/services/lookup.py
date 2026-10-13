"""Tenant-scoped lookups the topic services share: a group or user of the
actor's tenant (else 404), a grant subject, a group's lineage, and the live
clearance grants a membership change would gain or lift."""

from datetime import UTC, datetime
from uuid import UUID

from app.access.actor import Actor, require_clearance
from app.access.errors import NotFoundError
from app.access.evaluator import with_ancestors
from app.access.facts import KIND_CLEARANCE, SUBJECT_GROUP, as_utc
from app.access.models import Group
from app.access.repositories import AccessRepository
from app.identity import User


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _is_live(expires_at: datetime | None, now: datetime) -> bool:
    expiry = as_utc(expires_at)
    return expiry is None or expiry > now


class TenantLookup:
    """Reads scoped to the actor's tenant."""

    def __init__(self, repo: AccessRepository) -> None:
        self._repo = repo

    async def group(self, actor: Actor, group_id: UUID) -> Group:
        group = await self._repo.groups.group(group_id)
        if group is None or group.tenant != actor.tenant:
            msg = "No such group."
            raise NotFoundError(msg)
        return group

    async def user(self, actor: Actor, user_id: UUID) -> User:
        user = await self._repo.users.user(user_id)
        if user is None or user.tenant != actor.tenant:
            msg = "No such user."
            raise NotFoundError(msg)
        return user

    async def subject(self, actor: Actor, subject_type: str, subject_id: UUID) -> None:
        """The grant subject must exist in the actor's tenant."""
        if subject_type == SUBJECT_GROUP:
            await self.group(actor, subject_id)
        else:
            await self.user(actor, subject_id)

    async def lineage(self, actor: Actor, group_id: UUID | None) -> frozenset[UUID]:
        if group_id is None:
            return frozenset()
        groups = await self._repo.groups.tenant_groups(actor.tenant)
        return with_ancestors((group_id,), groups)

    async def require_clearances(
        self, actor: Actor, group_ids: frozenset[UUID], effect: str
    ) -> None:
        """`require_clearance` for every live clearance grant with `effect`
        on `group_ids`; the CLI (no policy) is exempt."""
        if actor.policy is None or not group_ids:
            return
        now = _utcnow()
        codes = {
            grant.target
            for grant in await self._repo.grants.group_grants(group_ids)
            if grant.target_kind == KIND_CLEARANCE
            and grant.effect == effect
            and _is_live(grant.expires_at, now)
        }
        for code in sorted(codes):
            require_clearance(actor, code)

"""Resolves a caller's Policy (spec §5.4, §8). Fails closed (spec §12)."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.cache import PolicyCache, shared_cache
from app.access.errors import PolicyUnavailableError
from app.access.evaluator import evaluate
from app.access.facts import PolicyInputs
from app.access.policy import Policy
from app.access.repository import AccessRepository
from app.access.schemas import GroupRefOut, MeAccessOut
from app.identity import Principal

logger = structlog.get_logger()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AccessService:
    def __init__(
        self,
        repo: AccessRepository,
        cache: PolicyCache,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._repo = repo
        self._cache = cache
        self._clock = clock

    async def policy_for(self, principal: Principal) -> Policy:
        return await self.policy_for_user(principal.user_id)

    async def policy_for_user(self, user_id: UUID) -> Policy:
        """The user's Policy. Any failure raises PolicyUnavailableError: deny."""
        try:
            return await self._resolve(user_id)
        except PolicyUnavailableError:
            logger.exception("access.policy_unavailable", user_id=str(user_id))
            raise
        except Exception as exc:
            logger.exception("access.policy_failed", user_id=str(user_id))
            msg = "The access check failed"
            raise PolicyUnavailableError(msg) from exc

    async def _resolve(self, user_id: UUID) -> Policy:
        # Read the version before the facts: a policy cached under version v
        # then never predates v.
        version = await self._repo.policy_version()
        now = self._clock()
        cached = self._cache.get(user_id, version, now)
        if cached is not None:
            return cached
        user = await self._repo.user_facts(user_id)
        if user is None:
            return Policy.deny_all(user_id, "", version)
        groups = await self._repo.tenant_groups(user.tenant)
        inputs = PolicyInputs(
            user=user,
            groups=groups,
            memberships=await self._repo.memberships(user_id),
            grants=await self._repo.grants_for(user_id, groups),
            policy_version=version,
        )
        policy = evaluate(inputs, now)
        self._cache.put(policy)
        return policy

    async def describe(self, policy: Policy) -> MeAccessOut:
        """What /me/access shows: role, capabilities, groups, any data at all.

        Built from the already-evaluated Policy (group_ids, managed_group_ids)
        so this can never disagree with it; tenant_groups is read only for names.
        """
        groups = await self._repo.tenant_groups(policy.tenant)
        refs = [
            GroupRefOut(
                id=gid,
                name=groups[gid].name,
                standing="manager" if gid in policy.managed_group_ids else "member",
            )
            for gid in policy.group_ids
            if gid in groups
        ]
        return MeAccessOut(
            role=policy.role,
            capabilities=sorted(policy.capabilities),
            groups=sorted(refs, key=lambda ref: ref.name),
            has_data_access=policy.has_data_access,
        )


async def policy_for(db: AsyncSession, principal: Principal) -> Policy:
    """Public entry point: the caller's Policy through the process-wide cache."""
    return await AccessService(AccessRepository(db), shared_cache()).policy_for(
        principal
    )

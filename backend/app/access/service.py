"""Resolves a caller's Policy (spec §5.4, §8). Fails closed (spec §12)."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.cache import PolicyCache, shared_cache
from app.access.errors import PolicyUnavailableError
from app.access.evaluator import evaluate
from app.access.facts import STATUS_ACTIVE, PolicyInputs, UserFacts
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
        inputs = await self._inputs(user, version)
        policy = evaluate(inputs, now)
        self._cache.put(policy)
        return policy

    async def capabilities_if_active(self, user_id: UUID) -> frozenset[str]:
        """The capabilities this user would have if active (D10: a disabled
        user is judged by the access they'd regain, never by deny_all's empty
        set). Not cached: the user's current status is not what this answers."""
        try:
            return await self._resolve_if_active(user_id)
        except PolicyUnavailableError:
            logger.exception("access.policy_unavailable", user_id=str(user_id))
            raise
        except Exception as exc:
            logger.exception("access.policy_failed", user_id=str(user_id))
            msg = "The access check failed"
            raise PolicyUnavailableError(msg) from exc

    async def _resolve_if_active(self, user_id: UUID) -> frozenset[str]:
        version = await self._repo.policy_version()
        now = self._clock()
        user = await self._repo.user_facts(user_id)
        if user is None:
            return frozenset()
        user = replace(user, status=STATUS_ACTIVE)
        inputs = await self._inputs(user, version)
        return evaluate(inputs, now).capabilities

    async def _inputs(self, user: UserFacts, version: int) -> PolicyInputs:
        groups = await self._repo.tenant_groups(user.tenant)
        return PolicyInputs(
            user=user,
            groups=groups,
            memberships=await self._repo.memberships(user.id),
            grants=await self._repo.grants_for(user.id, groups),
            policy_version=version,
        )

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

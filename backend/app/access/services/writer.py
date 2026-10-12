"""The shared write discipline for access administration.

Each write is one unit of work: the change, its rbac_changes row and the
policy_version bump commit together, so no cached policy can miss a change.
Every write also locks `policy_state` first
(`PolicyStateRepository.lock_for_write`), so concurrent admin writes serialize
and a losing write sees a 409 instead of racing past another write's
application-level checks; under that lock the actor's policy_version must
still be current, or the write is a 409 too.

A failed write rolls the session back, which expires loaded objects; reload
them before reuse.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel

from app.access.actor import Actor
from app.access.errors import ConflictError
from app.access.models import RbacChange
from app.access.repositories import AccessRepository

logger = structlog.get_logger()


def snapshot(row: SQLModel | None) -> dict[str, Any] | None:
    return None if row is None else row.model_dump(mode="json")


def rbac_change(
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


class AccessWriter:
    """Takes the write lock, re-checks the actor under it, and commits
    changes with their audit rows and one version bump. Every topic service
    writes through it."""

    def __init__(self, repo: AccessRepository) -> None:
        self._repo = repo

    @asynccontextmanager
    async def write(self, actor: Actor) -> AsyncGenerator[None]:
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
            version = await self._repo.state.lock_for_write()
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

    async def commit(self, *changes: RbacChange) -> None:
        """Stage every row, bump policy_version ONCE, commit, log each action."""
        for change in changes:
            self._repo.add(change)
        await self._repo.state.bump_version()
        await self._repo.commit()
        for change in changes:
            logger.info(
                "access.changed",
                action=change.action,
                object_id=change.object_id,
                via=change.via,
            )

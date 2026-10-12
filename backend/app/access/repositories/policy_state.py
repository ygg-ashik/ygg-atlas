"""The policy_state row (version, write lock) and the capability catalog mirror."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.access.errors import PolicyUnavailableError
from app.access.models import Capability, PolicyState


class PolicyStateRepository:
    """policy_state and the capability catalog."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def policy_version(self) -> int:
        version = (
            await self._db.execute(
                select(col(PolicyState.policy_version)).where(col(PolicyState.id) == 1)
            )
        ).scalar_one_or_none()
        if version is None:
            msg = "policy_state has no row"
            raise PolicyUnavailableError(msg)
        return version

    async def bump_version(self) -> None:
        # An UPDATE always executes through a cursor, so this is a CursorResult
        # (rowcount) at runtime; Session.execute only types it as the base Result.
        result = cast(
            "CursorResult[Any]",
            await self._db.execute(
                update(PolicyState)
                .where(col(PolicyState.id) == 1)
                .values(
                    policy_version=col(PolicyState.policy_version) + 1,
                    updated_at=datetime.now(UTC),
                )
            ),
        )
        if result.rowcount != 1:
            msg = "policy_state has no row"
            raise PolicyUnavailableError(msg)

    async def lock_for_write(self) -> int:
        """Serialize admin writes: take a row lock on policy_state.

        On Postgres, `FOR UPDATE` blocks a concurrent writer until this
        transaction commits or rolls back, so two admin writes never race
        past each other's application-level checks (duplicate names,
        parent cycles, in-use deletes). SQLite's dialect silently drops
        `FOR UPDATE` at compile time, but aiosqlite serializes writers to
        one connection anyway, so the same call is a safe no-op there.

        Returns the current policy_version, read under the lock.
        """
        version = (
            await self._db.execute(
                select(col(PolicyState.policy_version))
                .where(col(PolicyState.id) == 1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if version is None:
            msg = "policy_state has no row"
            raise PolicyUnavailableError(msg)
        return version

    async def ensure_policy_state(self) -> None:
        if await self._db.get(PolicyState, 1, populate_existing=True) is None:
            self._db.add(PolicyState(id=1, policy_version=1))
            await self._db.flush()

    async def sync_capabilities(self, catalog: Mapping[str, str]) -> None:
        existing = {
            c.code: c
            for c in (
                await self._db.execute(
                    select(Capability).execution_options(populate_existing=True)
                )
            ).scalars()
        }
        for code, description in catalog.items():
            row = existing.get(code) or Capability(code=code, description=description)
            row.description = description
            row.deprecated = False
            self._db.add(row)
        for code, row in existing.items():
            if code not in catalog:
                row.deprecated = True
                self._db.add(row)

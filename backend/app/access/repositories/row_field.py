"""Row and field controls: user attributes, label classes, scope dimensions."""

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.access.facts import BUILTIN_ATTRIBUTES
from app.access.models import LabelClassSetting, ScopeDimension, UserAttribute
from app.identity import User

logger = structlog.get_logger()


class RowFieldRepository:
    """Row and field controls: user attributes, label classes and the
    scope-dimension mirror."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def attributes_for(self, user_id: UUID) -> dict[str, str]:
        """The user's stored attributes plus the built-ins, which win (C11).

        Empty for an unknown user: there is nothing `$self` could resolve to.
        """
        user = await self._db.get(User, user_id, populate_existing=True)
        if user is None:
            return {}
        rows = (
            (
                await self._db.execute(
                    select(UserAttribute)
                    .where(col(UserAttribute.user_id) == user_id)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        attributes = {a.key: a.value for a in rows if a.key not in BUILTIN_ATTRIBUTES}
        attributes.update(email=user.email, user_id=str(user.id))
        return attributes

    async def self_attributes(self) -> dict[str, str]:
        """dimension -> the attribute its `$self` resolves to, from the mirror.

        The registry lints one `self` per dimension (C1); should the mirror
        disagree anyway, the dimension is left out, so `$self` on it resolves to
        nothing and the grant is skipped (fail closed).
        """
        rows = (
            await self._db.execute(
                select(ScopeDimension).execution_options(populate_existing=True)
            )
        ).scalars()
        declared: dict[str, set[str | None]] = {}
        for row in rows:
            declared.setdefault(row.dimension, set()).add(row.self_attribute)
        mapping: dict[str, str] = {}
        for dimension, attributes in sorted(declared.items()):
            if len(attributes) > 1:
                logger.error(
                    "access.self_attribute_conflict",
                    dimension=dimension,
                    attributes=sorted(a or "" for a in attributes),
                )
                continue
            (attribute,) = attributes
            if attribute is not None:
                mapping[dimension] = attribute
        return mapping

    async def label_modes(self) -> dict[str, tuple[str, int]]:
        """label class -> (mode, bucket_size), as stored; the evaluator validates."""
        rows = (
            await self._db.execute(
                select(LabelClassSetting).execution_options(populate_existing=True)
            )
        ).scalars()
        return {s.label_class: (s.mode, s.bucket_size) for s in rows}

    async def attribute(self, user_id: UUID, key: str) -> UserAttribute | None:
        return await self._db.get(UserAttribute, (user_id, key), populate_existing=True)

    async def list_attributes(self, user_id: UUID) -> list[UserAttribute]:
        stmt = (
            select(UserAttribute)
            .where(col(UserAttribute.user_id) == user_id)
            .order_by(col(UserAttribute.key))
            .execution_options(populate_existing=True)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def label_class(self, label_class: str) -> LabelClassSetting | None:
        return await self._db.get(
            LabelClassSetting, label_class, populate_existing=True
        )

    async def list_label_classes(self) -> list[LabelClassSetting]:
        stmt = (
            select(LabelClassSetting)
            .order_by(col(LabelClassSetting.label_class))
            .execution_options(populate_existing=True)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def scope_dimensions(self) -> list[ScopeDimension]:
        stmt = (
            select(ScopeDimension)
            .order_by(
                col(ScopeDimension.source),
                col(ScopeDimension.entity),
                col(ScopeDimension.dimension),
            )
            .execution_options(populate_existing=True)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def replace_scope_dimensions(
        self, rows: Iterable[tuple[str, str, str, str | None, str]]
    ) -> int:
        """Stage the mirror to hold exactly `rows`; returns how many rows changed.

        Unchanged rows are left alone (their synced_at too), so replacing with
        the same catalog is a no-op.
        """
        existing = {
            (r.source, r.entity, r.dimension): r for r in await self.scope_dimensions()
        }
        wanted = {(s, e, d): (attr, desc) for s, e, d, attr, desc in rows}
        changed = 0
        for key, row in existing.items():
            if key not in wanted:
                await self._db.delete(row)
                changed += 1
        for (source, entity, dimension), (attr, desc) in wanted.items():
            row = existing.get((source, entity, dimension))
            if row is not None and (row.self_attribute, row.description) == (
                attr,
                desc,
            ):
                continue
            row = row or ScopeDimension(
                source=source, entity=entity, dimension=dimension
            )
            row.self_attribute = attr
            row.description = desc
            row.synced_at = datetime.now(UTC)
            self._db.add(row)
            changed += 1
        return changed

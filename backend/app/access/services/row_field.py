"""Row and field controls: user attributes (D3.5), label classes (D3.9) and
the scope dimensions a row-scoped grant may use (D3.6)."""

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from app.access.actor import Actor
from app.access.catalog import ADMIN_GROUPS, ADMIN_USERS
from app.access.errors import ConflictError, InvalidChangeError, NotFoundError
from app.access.facts import (
    BUILTIN_ATTRIBUTES,
    MASK_MODES,
    MASKABLE_LABEL_CLASSES,
    MAX_ATTRIBUTE_VALUE,
    MAX_BUCKET_SIZE,
    SELF_TOKEN,
)
from app.access.models import LabelClassSetting, ScopeDimension, UserAttribute
from app.access.patterns import MAX_SEGMENTS, matches
from app.access.repositories import AccessRepository
from app.access.services.lookup import TenantLookup
from app.access.services.writer import AccessWriter, rbac_change
from app.identity import User

_ATTRIBUTE_KEY: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MASK_SUPPRESS: Final = "suppress"  # the mode with no stored row (C17)


def _utcnow() -> datetime:
    return datetime.now(UTC)


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


class RowFieldService:
    """Attributes, label classes and scope dimensions."""

    def __init__(self, repo: AccessRepository, writer: AccessWriter) -> None:
        self._repo = repo
        self._writer = writer
        self._lookup = TenantLookup(repo)

    async def list_attributes(self, actor: Actor, user_id: UUID) -> list[UserAttribute]:
        actor.require(ADMIN_USERS)
        user = await self._lookup.user(actor, user_id)
        return await self._repo.row_field.list_attributes(user.id)

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
        async with self._writer.write(actor):
            user = await self._lookup.user(actor, user_id)
            _not_self_attribute(actor, user)
            row = await self._repo.row_field.attribute(user.id, key)
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
            await self._writer.commit(
                rbac_change(
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
        async with self._writer.write(actor):
            user = await self._lookup.user(actor, user_id)
            _not_self_attribute(actor, user)
            row = await self._repo.row_field.attribute(user.id, key)
            if row is None:
                msg = f"That user has no attribute '{key}'."
                raise NotFoundError(msg)
            before = _attribute_snapshot(row)
            await self._repo.delete(row)
            await self._writer.commit(
                rbac_change(
                    actor,
                    "attribute.delete",
                    ("user_attribute", f"{user.id}:{key}"),
                    before,
                    None,
                )
            )

    async def list_label_classes(self, actor: Actor) -> list[LabelClassSetting]:
        """Both maskable classes (C12); an unset one shows as `suppress`, which
        is what the atlas does without a row (fail closed)."""
        actor.require(ADMIN_GROUPS)
        stored = {
            row.label_class: row
            for row in await self._repo.row_field.list_label_classes()
        }
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
        async with self._writer.write(actor):
            row = await self._repo.row_field.label_class(label_class)
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
            await self._writer.commit(
                rbac_change(
                    actor,
                    "label_class.update",
                    ("label_class", label_class),
                    before,
                    after,
                )
            )
        return row

    async def list_scope_dimensions(self, actor: Actor) -> list[ScopeDimension]:
        """The dimensions enabled plugins declare, for building scoped grants."""
        actor.require_any(ADMIN_GROUPS, ADMIN_USERS)
        return await self._repo.row_field.scope_dimensions()

    async def check_scope(
        self, pattern: str, scope: Mapping[str, Sequence[str]]
    ) -> None:
        """D3.6: every dimension is declared by at least one entity the pattern
        covers (for a one-entity pattern: by that entity), and `$self` only on
        a dimension that declares it. The mirror holds enabled plugins only, so
        a scope on a disabled plugin's data is rejected (fail closed)."""
        declared = {
            row.dimension
            for row in await self._repo.row_field.scope_dimensions()
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
        self_attributes = await self._repo.row_field.self_attributes()
        for dimension in sorted(scope):
            if SELF_TOKEN in scope[dimension] and dimension not in self_attributes:
                msg = (
                    f"'{dimension}' has no {SELF_TOKEN}: list the values to "
                    "match instead."
                )
                raise InvalidChangeError(msg)

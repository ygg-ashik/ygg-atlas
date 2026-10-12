"""Grants: list, create (with the no-self-widening and clearance checks) and revoke."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from app.access.actor import Actor, require_clearance
from app.access.catalog import ADMIN_GROUPS, ADMIN_USERS, CAPABILITIES, CLEARANCES
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.facts import (
    EFFECT_ALLOW,
    EFFECT_DENY,
    KIND_CAPABILITY,
    KIND_CLEARANCE,
    KIND_RESOURCE,
    SUBJECT_GROUP,
    SUBJECT_USER,
    as_utc,
    is_well_formed_scope,
)
from app.access.models import Grant, RbacChange
from app.access.patterns import InvalidPatternError, validate_pattern
from app.access.repositories import AccessRepository
from app.access.schemas import GrantCreate
from app.access.services.lookup import TenantLookup
from app.access.services.row_field import RowFieldService
from app.access.services.writer import AccessWriter, rbac_change, snapshot


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _grant_capability(subject_type: str) -> str:
    """Group grants are group administration; direct user grants are user admin."""
    return ADMIN_GROUPS if subject_type == SUBJECT_GROUP else ADMIN_USERS


def _validated_target(payload: GrantCreate, now: datetime) -> str:
    if payload.expires_at is not None and payload.expires_at <= now:
        msg = "The expiry must be in the future."
        raise InvalidChangeError(msg)
    if payload.subject_type == SUBJECT_USER and not payload.reason.strip():
        msg = "Direct user grants need a reason."
        raise InvalidChangeError(msg)
    if payload.target_kind == KIND_CLEARANCE:
        return _clearance_target(payload)
    if payload.target_kind == KIND_CAPABILITY:
        return _capability_target(payload)
    try:
        return validate_pattern(payload.target)
    except InvalidPatternError as exc:
        raise InvalidChangeError(str(exc)) from None


def _capability_target(payload: GrantCreate) -> str:
    if payload.subject_type != SUBJECT_USER:
        msg = (
            "Groups grant data, not actions. Change the user's role, or give the "
            "capability to a user directly."
        )
        raise InvalidChangeError(msg)
    if payload.target not in CAPABILITIES:
        msg = f"Unknown capability '{payload.target}'."
        raise InvalidChangeError(msg)
    return payload.target


def _clearance_target(payload: GrantCreate) -> str:
    """A field clearance: a known code, for a group or a user."""
    if payload.target not in CLEARANCES:
        msg = (
            f"Unknown clearance '{payload.target}'. "
            f"Clearances: {', '.join(CLEARANCES)}."
        )
        raise InvalidChangeError(msg)
    return payload.target


def _check_scope_shape(payload: GrantCreate) -> None:
    """Row scopes ride on resource allows only, and never in a
    shape the evaluator would treat as malformed: storing one would
    deny everything to everyone the grant applies to."""
    if payload.row_scope is None:
        return
    if payload.effect != EFFECT_ALLOW:
        msg = (
            "A deny can't carry a row scope: deny the whole resource, or "
            "narrow an allow instead."
        )
        raise InvalidChangeError(msg)
    if payload.target_kind != KIND_RESOURCE:
        msg = "Only data grants can carry a row scope."
        raise InvalidChangeError(msg)
    if not is_well_formed_scope(payload.row_scope):
        msg = "That row scope is not valid."
        raise InvalidChangeError(msg)


class GrantService:
    """Grant administration: group grants need admin:groups, user grants
    admin:users."""

    def __init__(
        self, repo: AccessRepository, writer: AccessWriter, row_field: RowFieldService
    ) -> None:
        self._repo = repo
        self._writer = writer
        self._lookup = TenantLookup(repo)
        self._row_field = row_field

    async def list_grants(
        self, actor: Actor, subject_type: Literal["group", "user"], subject_id: UUID
    ) -> list[Grant]:
        actor.require(_grant_capability(subject_type))
        await self._lookup.subject(actor, subject_type, subject_id)
        return await self._repo.grants.list_grants(subject_type, subject_id)

    async def create_grant(self, actor: Actor, payload: GrantCreate) -> Grant:
        actor.require(_grant_capability(payload.subject_type))
        if payload.subject_type == SUBJECT_USER and actor.user_id == payload.subject_id:
            # No self-grants; only capabilities you hold.
            msg = "You can't grant access to yourself. Ask another admin."
            raise AccessDeniedError(msg)
        now = _utcnow()
        target = _validated_target(payload, now)
        _check_scope_shape(payload)
        if payload.target_kind == KIND_CAPABILITY:
            # No self-grants; only capabilities you hold.
            actor.require(target)
        if payload.target_kind == KIND_CLEARANCE and payload.effect == EFFECT_ALLOW:
            require_clearance(actor, target)  # only clearances you hold
        async with self._writer.write(actor):
            grant, change = await self.stage_grant(actor, payload, now)
            await self._writer.commit(change)
        return grant

    async def stage_grant(
        self, actor: Actor, payload: GrantCreate, now: datetime
    ) -> tuple[Grant, RbacChange]:
        """Stage a new grant under the caller's `AccessWriter.write`; a
        duplicate is a 409."""
        actor.require(_grant_capability(payload.subject_type))
        if payload.subject_type == SUBJECT_USER and actor.user_id == payload.subject_id:
            # No self-grants; only capabilities you hold.
            msg = "You can't grant access to yourself. Ask another admin."
            raise AccessDeniedError(msg)
        target = _validated_target(payload, now)
        _check_scope_shape(payload)
        if payload.target_kind == KIND_CAPABILITY:
            # No self-grants; only capabilities you hold.
            actor.require(target)
        if payload.target_kind == KIND_CLEARANCE and payload.effect == EFFECT_ALLOW:
            require_clearance(actor, target)  # only clearances you hold
        await self._lookup.subject(actor, payload.subject_type, payload.subject_id)
        if payload.row_scope is not None:
            await self._row_field.check_scope(target, payload.row_scope)
        subject = (payload.subject_type, payload.subject_id)
        existing = await self._repo.grants.find_grant(
            subject, payload.effect, payload.target_kind, target
        )
        if existing is not None:
            expiry = as_utc(existing.expires_at)
            if expiry is not None and expiry <= now:
                msg = (
                    f"An expired grant {existing.id} for that target exists; "
                    "revoke it first."
                )
                raise ConflictError(msg)
            msg = "That grant already exists."
            raise ConflictError(msg)
        grant = Grant(
            subject_type=payload.subject_type,
            subject_id=payload.subject_id,
            effect=payload.effect,
            target_kind=payload.target_kind,
            target=target,
            reason=payload.reason.strip(),
            expires_at=payload.expires_at,
            created_by=actor.user_id,
            row_scope=payload.row_scope,
        )
        self._repo.add(grant)
        change = rbac_change(
            actor, "grant.create", ("grant", grant.id), None, snapshot(grant)
        )
        return grant, change

    async def revoke_grant(self, actor: Actor, grant_id: UUID) -> None:
        actor.require_any(ADMIN_GROUPS, ADMIN_USERS)
        async with self._writer.write(actor):
            grant = await self._repo.grants.grant(grant_id)
            if grant is None:
                msg = "No such grant."
                raise NotFoundError(msg)
            try:
                await self._lookup.subject(actor, grant.subject_type, grant.subject_id)
            except NotFoundError:
                # Hide whether a grant exists for a subject outside the actor's
                # tenant: the same "No such grant" as an unknown id. Checked
                # before the self-widening checks below, so a cross-tenant grant always
                # reads as "No such grant", never as an access-denied message.
                msg = "No such grant."
                raise NotFoundError(msg) from None
            if (
                grant.effect == EFFECT_DENY
                and grant.subject_type == SUBJECT_USER
                and grant.subject_id == actor.user_id
            ):
                # Revoking a deny widens access, same as a self-grant.
                msg = "You can't lift a restriction on yourself. Ask another admin."
                raise AccessDeniedError(msg)
            if grant.effect == EFFECT_DENY and grant.target_kind == KIND_CAPABILITY:
                # Revoking a deny widens access; only lift one you hold.
                actor.require(grant.target)
            if grant.effect == EFFECT_DENY and grant.target_kind == KIND_CLEARANCE:
                require_clearance(actor, grant.target)  # only one you hold
            actor.require(_grant_capability(grant.subject_type))
            before = snapshot(grant)
            await self._repo.delete(grant)
            await self._writer.commit(
                rbac_change(actor, "grant.revoke", ("grant", grant.id), before, None)
            )

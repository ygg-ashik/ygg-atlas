"""Users: the user list and detail, role and status changes, the effective
access preview and service accounts."""

from typing import Any
from uuid import UUID

import structlog

from app.access.actor import Actor
from app.access.catalog import ADMIN_USERS, ROLES, role_capabilities
from app.access.cursor import encode_cursor
from app.access.errors import AccessDeniedError, ConflictError, InvalidChangeError
from app.access.facts import SUBJECT_USER
from app.access.models import RbacChange
from app.access.policy import Policy
from app.access.repositories import AccessRepository
from app.access.schemas import (
    GrantOut,
    Page,
    UserDetailOut,
    UserGroupOut,
    UserOut,
    UserQuery,
    UserUpdate,
)
from app.access.service import AccessService
from app.access.services.lookup import TenantLookup
from app.access.services.paging import email_position
from app.access.services.writer import AccessWriter, rbac_change, snapshot
from app.identity import (
    REVOKED_USER_DISABLED,
    TokenVerifier,
    User,
    UserKind,
    UserStatus,
    revoke_user_tokens,
    service_account_email,
)

logger = structlog.get_logger()


def _not_self(actor: Actor, user: User) -> None:
    if actor.user_id is not None and actor.user_id == user.id:
        msg = "You can't change your own role or status. Ask another admin."
        raise ConflictError(msg)


def _check_role_escalation(actor: Actor, role: str) -> None:
    """A role can only be assigned if its capabilities are within the
    actor's own; the CLI actor (policy None) is unaffected."""
    if actor.policy is None:
        return
    if not role_capabilities(role) <= actor.policy.capabilities:
        msg = "You can't assign a role with more access than your own."
        raise AccessDeniedError(msg)


def _update_action(before: dict[str, Any]) -> str:
    keys = set(before)
    if keys == {"role"}:
        return "user.role"
    if keys == {"status"}:
        return "user.status"
    return "user.update"


def _apply_user_update(
    actor: Actor, user: User, payload: UserUpdate
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Stage role/status changes on `user`; return the (before, after) diff.

    Empty dicts mean no-op: nothing in `payload` actually changed anything.
    """
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    if payload.role is not None and payload.role != user.role:
        if payload.role not in ROLES:
            msg = f"Unknown role '{payload.role}'. Roles: {', '.join(ROLES)}."
            raise InvalidChangeError(msg)
        _check_role_escalation(actor, payload.role)
        before["role"] = user.role
        user.role = payload.role
        after["role"] = payload.role
    if payload.status is not None and payload.status != user.status:
        before["status"] = user.status
        user.status = payload.status
        after["status"] = payload.status
    return before, after


class UserService:
    """User administration (admin:users)."""

    def __init__(
        self,
        repo: AccessRepository,
        writer: AccessWriter,
        access: AccessService,
        verifier: TokenVerifier | None = None,
    ) -> None:
        self._repo = repo
        self._writer = writer
        self._lookup = TenantLookup(repo)
        self._access = access
        self._verifier = verifier

    async def list_users(self, actor: Actor, query: UserQuery) -> Page[UserOut]:
        """The tenant's users by email (keyset on (email, id)), filtered."""
        actor.require(ADMIN_USERS)
        rows = await self._repo.users.list_users(
            actor.tenant, query, email_position(query.cursor)
        )
        page = rows[: query.limit]
        next_cursor = None
        if len(rows) > query.limit:
            next_cursor = encode_cursor(page[-1].email, page[-1].id)
        return Page[UserOut](
            items=[UserOut.model_validate(u) for u in page], next_cursor=next_cursor
        )

    async def user_detail(self, actor: Actor, user_id: UUID) -> UserDetailOut:
        """One user with their direct groups, direct grants and pending requests."""
        actor.require(ADMIN_USERS)  # before any lookup: no probing for user ids
        user = await self._lookup.user(actor, user_id)
        groups = await self._repo.groups.tenant_groups(actor.tenant)
        memberships = [
            UserGroupOut(id=gid, name=groups[gid].name, standing=standing)
            for gid, standing in (await self._repo.groups.memberships(user.id)).items()
            if gid in groups
        ]
        grants = await self._repo.grants.list_grants(SUBJECT_USER, user.id)
        return UserDetailOut(
            **UserOut.model_validate(user).model_dump(),
            groups=sorted(memberships, key=lambda g: (g.name, g.id)),
            direct_grants=[GrantOut.model_validate(g) for g in grants],
            pending_requests=await self._repo.requests.count_pending(user.id),
        )

    async def update_user(
        self, actor: Actor, user_id: UUID, payload: UserUpdate
    ) -> User:
        actor.require(ADMIN_USERS)  # before any lookup: no probing for user ids
        if payload.role is None and payload.status is None:
            msg = "Nothing to change: send a role or a status."
            raise InvalidChangeError(msg)
        async with self._writer.write(actor):
            user, change = await self.stage_user_update(actor, user_id, payload)
            if change is None:
                await self._repo.commit()  # release the lock; nothing changed
                return user
            after = change.after or {}
            await self._writer.commit(change)
        if after.get("status") == UserStatus.DISABLED:
            await self._end_firebase_sessions(user)
            await revoke_user_tokens(
                user.id,
                reason=REVOKED_USER_DISABLED,
                actor_user_id=actor.user_id,
                via="cli" if actor.via == "cli" else "api",
            )
        return user

    async def stage_user_update(
        self, actor: Actor, user_id: UUID, payload: UserUpdate
    ) -> tuple[User, RbacChange | None]:
        """Stage a role/status change under the caller's `AccessWriter.write`;
        None is no-op."""
        actor.require(ADMIN_USERS)
        user = await self._lookup.user(actor, user_id)
        _not_self(actor, user)
        await self._check_not_above_actor(actor, user)
        before, after = _apply_user_update(actor, user, payload)
        if not before:
            return user, None
        self._repo.add(user)
        change = rbac_change(
            actor, _update_action(before), ("user", user.id), before, after
        )
        return user, change

    async def effective_access(self, actor: Actor, user_id: UUID) -> Policy:
        """The user's evaluated Policy, for the preview."""
        actor.require(ADMIN_USERS)
        user = await self._lookup.user(actor, user_id)
        return await self._access.policy_for_user(user.id)

    async def create_service_account(self, actor: Actor, name: str, role: str) -> User:
        """A service identity owned by the actor; audited and versioned."""
        actor.require(ADMIN_USERS)
        if role not in ROLES:
            msg = f"Unknown role '{role}'. Roles: {', '.join(ROLES)}."
            raise InvalidChangeError(msg)
        _check_role_escalation(actor, role)
        email = service_account_email(name)
        if email is None:
            msg = "Use 3-40 letters, digits or dashes for the service account name."
            raise InvalidChangeError(msg)
        async with self._writer.write(actor):
            if await self._repo.users.user_by_email(email) is not None:
                msg = f"A service account '{email}' already exists."
                raise ConflictError(msg)
            user = User(
                email=email,
                display_name=name.strip(),
                kind=UserKind.SERVICE,
                role=role,
                owner_user_id=actor.user_id,
                tenant=actor.tenant,
            )
            self._repo.add(user)
            await self._writer.commit(
                rbac_change(
                    actor,
                    "service_account.create",
                    ("user", user.id),
                    None,
                    snapshot(user),
                )
            )
        return user

    async def _check_not_above_actor(self, actor: Actor, user: User) -> None:
        """Nobody changes the role or status of a user whose effective
        capabilities exceed their own (the CLI actor, policy None, is unaffected).

        Judged by the capabilities the target would have if active: a disabled
        user's real Policy is deny_all with empty capabilities, which would
        otherwise let anyone with admin:users re-enable or re-role them.
        """
        if actor.policy is None:
            return
        target_capabilities = await self._access.capabilities_if_active(user.id)
        if not target_capabilities <= actor.policy.capabilities:
            msg = "You can't change a user with more access than your own."
            raise AccessDeniedError(msg)

    async def _end_firebase_sessions(self, user: User) -> None:
        if self._verifier is None or not user.firebase_uid:
            return
        try:
            await self._verifier.revoke(user.firebase_uid)
        except Exception:
            # Status is enforced on every request; revocation only ends sessions sooner.
            logger.exception("access.revoke_failed", user_id=str(user.id))
        else:
            logger.info("access.sessions_revoked", user_id=str(user.id))

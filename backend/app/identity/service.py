"""Identity use cases: who is calling, and may they use atlas at all.

Data access goes through UserRepository; nothing here knows about HTTP.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.identity.errors import ForbiddenError, UnauthenticatedError
from app.identity.models import User, UserKind, UserStatus
from app.identity.principal import AuthMethod, Principal
from app.identity.repository import UserRepository
from app.identity.tokens import TokenVerifier, VerifiedToken

logger = structlog.get_logger()

LAST_SEEN_INTERVAL = timedelta(minutes=5)
# Spec §3: web sign-in is Google only, so Workspace SSO, 2FA and offboarding apply.
GOOGLE_PROVIDER = "google.com"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(moment: datetime) -> datetime:
    """SQLite returns naive datetimes; every stored timestamp is UTC (CLAUDE.md)."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def to_principal(user: User, auth_method: AuthMethod) -> Principal:
    return Principal(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        kind=user.kind,
        tenant=user.tenant,
        auth_method=auth_method,
    )


class IdentityService:
    def __init__(
        self,
        users: UserRepository,
        settings: Settings,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._users = users
        self._settings = settings
        self._clock = clock

    async def resolve_web(self, token: VerifiedToken) -> Principal:
        """Turn a verified Google sign-in into a Principal, creating the user once."""
        self._check_sign_in(token)
        self._check_session_age(token)
        user = await self._find_or_link(token)
        if user.status != UserStatus.ACTIVE:
            logger.warning("identity.disabled_user", user_id=str(user.id))
            msg = "Your atlas access is disabled. Contact an admin."
            raise ForbiddenError(msg)
        await self._touch(user)
        return to_principal(user, "web")

    async def ensure_dev_user(self) -> Principal:
        """Local development only (AUTH_DISABLED): one viewer, created once.

        Admin rights come only from BOOTSTRAP_ADMINS, even in development.
        """
        email = f"dev@{self._settings.allowed_email_domain.lower()}"
        user = await self._users.get_by_email(email)
        if user is None:
            user = await self._users.create_or_get(
                User(email=email, display_name="Dev User")
            )
        return to_principal(user, "dev")

    async def disable_user(self, user_id: UUID, verifier: TokenVerifier) -> User:
        """Block the user on the next request and end their Firebase sessions."""
        user = await self._users.get(user_id)
        if user is None:
            msg = f"No user {user_id}"
            raise LookupError(msg)
        user.status = UserStatus.DISABLED
        user = await self._users.save(user)
        if user.firebase_uid:
            await verifier.revoke(user.firebase_uid)
        logger.info("identity.user_disabled", user_id=str(user.id))
        return user

    def _check_sign_in(self, token: VerifiedToken) -> None:
        domain = self._settings.allowed_email_domain.lower()
        if not token.email_verified or not token.email.lower().endswith(f"@{domain}"):
            logger.warning("identity.domain_rejected")
            msg = f"Use your @{domain} account."
            raise ForbiddenError(msg)
        if token.sign_in_provider != GOOGLE_PROVIDER:
            logger.warning(
                "identity.provider_rejected", provider=token.sign_in_provider
            )
            msg = f"Sign in with your @{domain} Google account."
            raise ForbiddenError(msg)

    def _check_session_age(self, token: VerifiedToken) -> None:
        signed_in = datetime.fromtimestamp(token.auth_time, tz=UTC)
        max_age = timedelta(hours=self._settings.session_max_age_hours)
        if self._clock() - signed_in > max_age:
            msg = "Your session has expired. Sign in again."
            raise UnauthenticatedError(msg)

    async def _find_or_link(self, token: VerifiedToken) -> User:
        user = await self._users.get_by_firebase_uid(token.uid)
        if user is not None:
            return user
        user = await self._users.get_by_email(token.email)
        if user is None:
            logger.info("identity.user_created")
            return await self._users.create_or_get(
                User(email=token.email, firebase_uid=token.uid, display_name=token.name)
            )
        if user.status != UserStatus.ACTIVE:
            return user  # rejected by the caller; never mutate a disabled row
        if user.firebase_uid and user.firebase_uid != token.uid:
            # e.g. a deleted and recreated Google account; same verified mailbox.
            logger.warning("identity.firebase_uid_relinked", user_id=str(user.id))
        user.firebase_uid = token.uid
        if not user.display_name:
            user.display_name = token.name
        return await self._users.save(user)

    async def _touch(self, user: User) -> None:
        now = self._clock()
        last = user.last_seen_at
        if last is None or now - _as_utc(last) >= LAST_SEEN_INTERVAL:
            user.last_seen_at = now
            await self._users.save(user)


async def service_principal(db: AsyncSession, email: str) -> Principal | None:
    """The Principal for an active service identity, or None (fail closed)."""
    user = await UserRepository(db).get_by_email(email)
    if user is None or user.kind != UserKind.SERVICE:
        return None
    if user.status != UserStatus.ACTIVE:
        return None
    return to_principal(user, "service")

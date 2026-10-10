"""Personal and service tokens, connected apps and the single bearer door (D3, D20).

Interface first (D35): auth phase 4 Task 2 lands these signatures so the MCP edge and
the access hooks can code against them; Task 3 fills the bodies. Raw secrets exist
only in `IssuedToken.raw`, once, and are never logged, stored or put in a repr.
"""

import re
from collections.abc import Callable, Collection
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.identity.api_tokens import (
    BEARER_KINDS,
    EVENT_FAMILY_REVOKED,
    EVENT_TOKEN_CREATED,
    EVENT_TOKEN_REVOKED,
    EVENT_TOKENS_REVOKED_ALL,
    LAST_USED_INTERVAL,
    MAX_LIVE_PATS,
    MAX_TOKEN_DAYS,
    UNNAMED_CLIENT,
    CredentialActor,
    CredentialVia,
    TokenKind,
    display_prefix,
    hash_secret,
    kind_of,
    mint,
)
from app.identity.errors import (
    CredentialLimitError,
    CredentialNotFoundError,
    CredentialRuleError,
    ForbiddenError,
)
from app.identity.models import ApiToken, CredentialEvent, User, UserKind, UserStatus
from app.identity.principal import AuthMethod, Principal
from app.identity.repository import CredentialRepository, UserRepository
from app.identity.service import to_principal
from app.identity.tokens import ExpiredTokenError, InvalidTokenError

logger = structlog.get_logger()

SERVICE_ACCOUNT_DOMAIN: Final = "atlas.internal"
_SLUG_SEPARATORS: Final = re.compile(r"[^a-z0-9]+")
_SLUG_MIN, _SLUG_MAX = 3, 40
_NAME_MAX: Final = 100
# The only things a rejected bearer is ever told (conventions, invariant 2).
_INVALID: Final = "invalid token"
_EXPIRED: Final = "expired"
_DISABLED: Final = "Your atlas access is disabled. Contact an admin."
_NO_TOKEN: Final = "No such token."  # noqa: S105  # a message, not a secret
_AUTH_METHOD: Final[dict[TokenKind, AuthMethod]] = {
    TokenKind.PAT: "pat",
    TokenKind.SERVICE: "service",
    TokenKind.OAUTH_ACCESS: "oauth",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(moment: datetime) -> datetime:
    """SQLite returns naive datetimes; every stored timestamp is UTC (CLAUDE.md)."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A freshly minted token: the stored row and the raw value, shown once (D3)."""

    token: ApiToken
    raw: str = field(repr=False)  # never logged or stored


@dataclass(frozen=True, slots=True)
class AuthenticatedBearer:
    """What the bearer door hands the MCP token verifier (C11)."""

    principal: Principal  # auth_method oauth|pat|service, token_id and client_id set
    expires_at: datetime
    audience: str | None  # OAuth: the bound audience; PAT/service: None (use current)
    display_prefix: str


@dataclass(frozen=True, slots=True)
class ConnectedApp:
    """One OAuth consent (a token family) that can still refresh."""

    family_id: UUID
    client_id: str
    client_name: str  # UNNAMED_CLIENT when the client registered none
    redirect_host: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime


def service_account_email(name: str) -> str | None:
    """The `svc-<slug>@atlas.internal` email for a service-account name, or None when
    the name is over 100 characters (it becomes the display name) or the slug is not
    3-40 lowercase letters, digits or dashes (D13, ruling C5)."""
    cleaned = name.strip()
    if len(cleaned) > _NAME_MAX:
        return None
    slug = _SLUG_SEPARATORS.sub("-", cleaned.lower()).strip("-")
    if not _SLUG_MIN <= len(slug) <= _SLUG_MAX:
        return None
    return f"svc-{slug}@{SERVICE_ACCOUNT_DOMAIN}"


async def authenticate_bearer(
    db: AsyncSession, raw: str, now: datetime | None = None
) -> AuthenticatedBearer:
    """Raises InvalidTokenError (unknown, revoked, wrong kind, refresh token, revoked
    client), its subtype ExpiredTokenError (expiry is the only fault) or
    ForbiddenError (user disabled). Never includes token material in the message."""
    moment = now or _utcnow()
    candidate = raw.strip()
    kind = kind_of(candidate)  # rejected before any DB work (D3)
    if kind is None or kind not in BEARER_KINDS:  # refresh tokens are never bearers
        raise _rejected("malformed" if kind is None else "not_a_bearer", None)
    prefix = display_prefix(candidate)
    creds = CredentialRepository(db)
    row = await creds.token_by_hash(hash_secret(candidate))
    if row is None:
        raise _rejected("unknown", prefix)
    reason = _dead_reason(row, kind, moment)
    if reason is not None:
        raise _rejected(reason, prefix)
    user = _active_owner(await UserRepository(db).get(row.user_id), kind, prefix)
    if kind is TokenKind.OAUTH_ACCESS:
        await _require_live_client(creds, row, prefix)
    await _touch(creds, row, moment)
    principal = replace(
        to_principal(user, _AUTH_METHOD[kind]),
        token_id=row.id,
        client_id=row.client_id,
    )
    return AuthenticatedBearer(principal, _as_utc(row.expires_at), row.audience, prefix)


def _rejected(reason: str, prefix: str | None) -> InvalidTokenError:
    """The one rejection: the reason goes to the log, never to the caller. Expiry
    of an otherwise live bearer is the one subtype (`ExpiredTokenError`), same text."""
    logger.info("identity.bearer_rejected", reason=reason, prefix=prefix)
    if reason == _EXPIRED:
        return ExpiredTokenError(_INVALID)
    return InvalidTokenError(_INVALID)


def _dead_reason(row: ApiToken, kind: TokenKind, moment: datetime) -> str | None:
    if row.kind != kind:
        return "kind_mismatch"
    if row.revoked_at is not None:
        return "revoked"
    if _as_utc(row.expires_at) <= moment:
        return _EXPIRED
    return None


def _active_owner(user: User | None, kind: TokenKind, prefix: str) -> User:
    if user is None:
        raise _rejected("no_user", prefix)
    if user.status != UserStatus.ACTIVE:
        logger.info("identity.bearer_rejected", reason="user_disabled", prefix=prefix)
        raise ForbiddenError(_DISABLED, "user_disabled")
    expected = UserKind.SERVICE if kind is TokenKind.SERVICE else UserKind.HUMAN
    if user.kind != expected:
        raise _rejected("user_kind", prefix)
    return user


async def _require_live_client(
    creds: CredentialRepository, row: ApiToken, prefix: str
) -> None:
    client = None if row.client_id is None else await creds.client(row.client_id)
    if client is None or client.revoked_at is not None:
        raise _rejected("client_revoked", prefix)


async def _touch(creds: CredentialRepository, row: ApiToken, moment: datetime) -> None:
    """last_used_at, written at most every LAST_USED_INTERVAL (D3)."""
    last = row.last_used_at
    if last is not None and moment - _as_utc(last) < LAST_USED_INTERVAL:
        return
    await creds.touch_token(row.id, moment)
    await creds.commit()


async def principal_for_user(db: AsyncSession, user_id: UUID) -> Principal | None:
    """Active users only; auth_method 'service' for service accounts, 'pat' otherwise.
    Used by the MCP edge to evaluate a user's Policy (eligibility, D34)."""
    user = await UserRepository(db).get(user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        return None
    return to_principal(user, "service" if user.kind == UserKind.SERVICE else "pat")


async def tenant_of_user(db: AsyncSession, user_id: UUID) -> str | None:
    """The tenant of any user, whatever their status; None for an unknown id. Lets an
    admin clean up a disabled user's credentials (D18 hook failure)."""
    user = await UserRepository(db).get(user_id)
    return None if user is None else user.tenant


async def revoke_user_tokens(
    user_id: UUID,
    *,
    reason: str,
    actor_user_id: UUID | None,
    via: CredentialVia,
) -> None:
    """Post-commit hook for AccessAdmin.update_user (D18, C5): opens its own session
    from get_session_factory(), revokes every token of every kind, writes
    tokens.revoked_all, and never raises (logs identity.revoke_all_failed). The bearer
    door refuses disabled users regardless."""
    try:
        async with get_session_factory()() as db:
            await TokenService(db).revoke_all_tokens(
                user_id, reason=reason, actor=CredentialActor(actor_user_id, via)
            )
    except Exception as exc:  # a hook: the door refuses disabled users anyway
        logger.error(
            "identity.revoke_all_failed",
            user_id=str(user_id),
            error=type(exc).__name__,
        )


@dataclass(frozen=True, slots=True)
class _TokenRequest:
    """One PAT or service-token mint, validated by TokenService._issue."""

    user_id: UUID
    kind: TokenKind
    name: str
    expires_in_days: int | None
    actor: CredentialActor
    default_days: int
    max_days: int


def _token_name(name: str) -> str:
    cleaned = name.strip()
    if not 1 <= len(cleaned) <= _NAME_MAX:
        msg = f"Name the token in 1-{_NAME_MAX} characters."
        raise CredentialRuleError(msg)
    return cleaned


def _lifetime(request: _TokenRequest) -> timedelta:
    limit = min(request.max_days, MAX_TOKEN_DAYS)
    days = (
        request.default_days
        if request.expires_in_days is None
        else request.expires_in_days
    )
    if not 1 <= days <= limit:
        msg = f"A token lasts 1-{limit} days."
        raise CredentialRuleError(msg)
    return timedelta(days=days)


def _redirect_host(uris: tuple[str, ...]) -> str:
    return (urlsplit(uris[0]).hostname or "") if uris else ""


class TokenService:
    """PATs and service tokens for the self-service and admin APIs and the CLI."""

    def __init__(
        self, db: AsyncSession, clock: Callable[[], datetime] = _utcnow
    ) -> None:
        self._creds = CredentialRepository(db)
        self._users = UserRepository(db)
        self._clock = clock

    async def create_pat(
        self,
        user_id: UUID,
        *,
        name: str,
        expires_in_days: int | None,
        actor: CredentialActor,
        default_days: int,
        max_days: int,
    ) -> IssuedToken:
        """An active human's personal token: name 1-100 chars, days in 1..max_days
        (default `default_days`), at most MAX_LIVE_PATS live. Writes token.created."""
        return await self._issue(
            _TokenRequest(
                user_id,
                TokenKind.PAT,
                name,
                expires_in_days,
                actor,
                default_days,
                max_days,
            )
        )

    async def create_service_token(
        self,
        service_user_id: UUID,
        *,
        name: str,
        expires_in_days: int | None,
        actor: CredentialActor,
        default_days: int,
        max_days: int,
    ) -> IssuedToken:
        """A token for an active service account; same day rules, no live cap."""
        return await self._issue(
            _TokenRequest(
                service_user_id,
                TokenKind.SERVICE,
                name,
                expires_in_days,
                actor,
                default_days,
                max_days,
            )
        )

    async def _issue(self, request: _TokenRequest) -> IssuedToken:
        name = _token_name(request.name)
        lifetime = _lifetime(request)
        await self._require_holder(request.user_id, request.kind)
        now = self._clock()
        if (
            request.kind is TokenKind.PAT
            and await self._creds.count_live(request.user_id, request.kind, now)
            >= MAX_LIVE_PATS
        ):
            msg = (
                f"You already have {MAX_LIVE_PATS} live personal tokens. "
                "Revoke one first."
            )
            raise CredentialLimitError(msg)
        raw = mint(request.kind)
        prefix = display_prefix(raw)
        token = ApiToken(
            user_id=request.user_id,
            kind=request.kind,
            token_hash=hash_secret(raw),
            prefix=prefix,
            name=name,
            created_by=request.actor.user_id,
            created_at=now,
            expires_at=now + lifetime,
        )
        self._creds.add(token)
        self._creds.add(
            self._event(
                EVENT_TOKEN_CREATED,
                request.actor,
                user_id=request.user_id,
                token_id=token.id,
                details={
                    "kind": str(request.kind),
                    "name": name,
                    "prefix": prefix,
                    "via": request.actor.via,
                },
            )
        )
        await self._creds.commit()
        logger.info(
            "identity.token_created",
            token_id=str(token.id),
            kind=str(request.kind),
            prefix=prefix,
            via=request.actor.via,
        )
        return IssuedToken(token=token, raw=raw)

    async def _require_holder(self, user_id: UUID, kind: TokenKind) -> None:
        user = await self._users.get(user_id)
        expected = UserKind.SERVICE if kind is TokenKind.SERVICE else UserKind.HUMAN
        if user is None or user.status != UserStatus.ACTIVE or user.kind != expected:
            msg = (
                "Service tokens need an active service account."
                if kind is TokenKind.SERVICE
                else "Personal tokens are for active people only."
            )
            raise CredentialRuleError(msg)

    async def list_tokens(
        self,
        *,
        tenant: str,
        user_id: UUID | None = None,
        kinds: Collection[TokenKind] = (TokenKind.PAT, TokenKind.SERVICE),
        include_revoked: bool = False,
    ) -> list[ApiToken]:
        """Tokens in `tenant`, newest first; only one user's when `user_id` is set."""
        return await self._creds.list_tokens(
            tenant=tenant,
            kinds=[str(kind) for kind in kinds],
            user_id=user_id,
            include_revoked=include_revoked,
        )

    async def revoke_token(
        self,
        token_id: UUID,
        *,
        reason: str,
        actor: CredentialActor,
        owner_id: UUID | None = None,
        tenant: str | None = None,
    ) -> None:
        """Idempotent. Another owner's or tenant's token is CredentialNotFoundError
        (no existence probing). Writes token.revoked."""
        token = await self._creds.token(token_id, fresh=True)
        if token is None or (owner_id is not None and token.user_id != owner_id):
            raise CredentialNotFoundError(_NO_TOKEN)
        if tenant is not None:
            owner = await self._users.get(token.user_id)
            if owner is None or owner.tenant != tenant:
                raise CredentialNotFoundError(_NO_TOKEN)
        if token.family_id is not None:
            # An OAuth row alone is not the credential: its live refresh token
            # would mint a fresh pair. The whole family goes, under its lock.
            await self._revoke_family_rows(
                token.family_id,
                reason=reason,
                actor=actor,
                user_id=token.user_id,
                client_id=token.client_id,
                token_id=token.id,
            )
            return
        if not await self._creds.revoke_token(token.id, reason, self._clock()):
            return  # already revoked: nothing changed, nothing to log
        self._creds.add(
            self._event(
                EVENT_TOKEN_REVOKED,
                actor,
                user_id=token.user_id,
                token_id=token.id,
                client_id=token.client_id,
                details={"kind": token.kind, "prefix": token.prefix, "reason": reason},
            )
        )
        await self._creds.commit()
        logger.info(
            "identity.token_revoked",
            token_id=str(token.id),
            reason=reason,
            via=actor.via,
        )

    async def revoke_all_tokens(
        self, user_id: UUID, *, reason: str, actor: CredentialActor
    ) -> int:
        """Every kind; one tokens.revoked_all event with the count and reason."""
        now = self._clock()
        count = await self._creds.revoke_user_tokens(user_id, reason, now)
        codes = await self._creds.spend_user_codes(user_id, now)
        self._creds.add(
            self._event(
                EVENT_TOKENS_REVOKED_ALL,
                actor,
                user_id=user_id,
                details={"count": count, "codes": codes, "reason": reason},
            )
        )
        await self._creds.commit()
        logger.info(
            "identity.tokens_revoked_all",
            user_id=str(user_id),
            count=count,
            reason=reason,
            via=actor.via,
        )
        return count

    async def list_connected_apps(self, user_id: UUID) -> list[ConnectedApp]:
        """One entry per OAuth family with a live refresh token."""
        rows = await self._creds.connected_apps(user_id, self._clock())
        return [
            ConnectedApp(
                family_id=row.family_id,
                client_id=row.client_id,
                client_name=row.client_name or UNNAMED_CLIENT,
                redirect_host=_redirect_host(row.redirect_uris),
                created_at=_as_utc(row.created_at),
                last_used_at=None
                if row.last_used_at is None
                else _as_utc(row.last_used_at),
                expires_at=_as_utc(row.expires_at),
            )
            for row in rows
        ]

    async def revoke_family(
        self,
        family_id: UUID,
        *,
        reason: str,
        actor: CredentialActor,
        owner_id: UUID | None = None,
    ) -> None:
        """Revokes every live row of the family; writes oauth.family_revoked.

        With `owner_id`, the family must be one of that user's connected apps, or it
        is CredentialNotFoundError. Without it (operators), a dead family is a no-op.
        """
        client_id: str | None = None
        if owner_id is not None:
            apps = await self._creds.connected_apps(owner_id, self._clock())
            app = next((a for a in apps if a.family_id == family_id), None)
            if app is None:
                msg = "No such connected app."
                raise CredentialNotFoundError(msg)
            client_id = app.client_id
        await self._revoke_family_rows(
            family_id,
            reason=reason,
            actor=actor,
            user_id=owner_id,
            client_id=client_id,
        )

    async def _revoke_family_rows(
        self,
        family_id: UUID,
        *,
        reason: str,
        actor: CredentialActor,
        user_id: UUID | None,
        client_id: str | None,
        token_id: UUID | None = None,
    ) -> None:
        """Revokes the family's live rows (the repository takes the family lock
        first, the order issuers use after the client row) and writes
        oauth.family_revoked; a dead family changes and logs nothing."""
        count = await self._creds.revoke_family(family_id, reason, self._clock())
        if count == 0:
            await self._creds.commit()  # nothing staged; ends the family lock
            return
        self._creds.add(
            self._event(
                EVENT_FAMILY_REVOKED,
                actor,
                user_id=user_id,
                token_id=token_id,
                client_id=client_id,
                details={"family_id": str(family_id), "count": count, "reason": reason},
            )
        )
        await self._creds.commit()
        logger.info(
            "identity.family_revoked",
            family_id=str(family_id),
            count=count,
            reason=reason,
            via=actor.via,
        )

    async def list_events(
        self, *, tenant: str, user_id: UUID | None = None, limit: int = 100
    ) -> list[CredentialEvent]:
        """credential_events in `tenant`, newest first."""
        return await self._creds.list_events(
            tenant=tenant, user_id=user_id, limit=limit
        )

    def _event(
        self,
        event: str,
        actor: CredentialActor,
        *,
        user_id: UUID | None,
        token_id: UUID | None = None,
        client_id: str | None = None,
        details: dict[str, Any],
    ) -> CredentialEvent:
        return CredentialEvent(
            at=self._clock(),
            event=event,
            user_id=user_id,
            actor_user_id=actor.user_id,
            via=actor.via,
            token_id=token_id,
            client_id=client_id,
            details=details,
        )

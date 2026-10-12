"""The token-family discipline every grant step shares: the one lock order, the
per-issue checks, issuing an access/refresh pair, revoking a whole family, and
turning database errors into GrantUnavailableError (fail closed)."""

from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.identity.api_tokens import (
    EVENT_FAMILY_REVOKED,
    EVENT_REUSE_DETECTED,
    REVOKED_AUDIENCE_CHANGED,
    REVOKED_CLIENT,
    REVOKED_CODE_REUSE,
    REVOKED_CROSS_CLIENT,
    REVOKED_NO_MCP_USE,
    REVOKED_REFRESH_REUSE,
    REVOKED_USER_DISABLED,
    TokenKind,
    display_prefix,
    hash_secret,
    mint,
)
from app.identity.models import ApiToken, CredentialEvent, UserKind, UserStatus
from app.identity.oauth.clients import ClientService
from app.identity.oauth.config import OAuthConfig
from app.identity.oauth.errors import (
    DEAD_REFRESH,
    EligibilityUnavailableError,
    GrantUnavailableError,
    OAuthGrantError,
)
from app.identity.oauth.urls import same_audience
from app.identity.oauth.values import Eligibility, ReuseKind, TokenPair
from app.identity.repository import CredentialRepository, UserRepository

logger = structlog.get_logger()

_REUSE_REASONS: Final = frozenset(
    {REVOKED_CODE_REUSE, REVOKED_REFRESH_REUSE, REVOKED_CROSS_CLIENT}
)


@dataclass(frozen=True, slots=True)
class Family:
    """One consent's token family: who it belongs to and through which client."""

    family_id: UUID
    user_id: UUID
    client_id: str


def _mint_row(
    kind: TokenKind, family: Family, audience: str, now: datetime, ttl: timedelta
) -> tuple[ApiToken, str]:
    """A new token of `kind` in `family`: the row to store and the raw value."""
    raw = mint(kind)
    row = ApiToken(
        user_id=family.user_id,
        kind=kind,
        token_hash=hash_secret(raw),
        prefix=display_prefix(raw),
        client_id=family.client_id,
        family_id=family.family_id,
        audience=audience,
        created_at=now,
        expires_at=now + ttl,
    )
    return row, raw


def presenter(owner_client_id: str, presented_by: str) -> dict[str, str]:
    """Forensics for a reuse event: who presented the credential, when not its own
    client (the event's client_id stays the family's client)."""
    if presented_by == owner_client_id:
        return {}
    return {"presented_by_client_id": presented_by}


async def _is_eligible(eligible: Eligibility, user_id: UUID) -> bool:
    """False only for a definite "not eligible"; a failed check raises
    EligibilityUnavailableError, so it never revokes a family as `no_mcp_use`."""
    try:
        return await eligible(user_id)
    except EligibilityUnavailableError:
        raise
    except Exception as exc:  # could not check: fail closed, but revoke nothing
        logger.error("oauth.eligibility_check_failed", error=type(exc).__name__)
        raise EligibilityUnavailableError from None


class TokenFamilies:
    """Locks, checks, issues into and revokes token families. Shared by the code
    exchange, refresh rotation and revocation steps; none re-implements it."""

    def __init__(
        self,
        creds: CredentialRepository,
        users: UserRepository,
        config: OAuthConfig,
        clock: Callable[[], datetime],
        clients: ClientService,
    ) -> None:
        self._creds = creds
        self._users = users
        self._config = config
        self._clock = clock
        self._clients = clients

    async def enter(self, family: Family) -> datetime:
        """Takes the locks an issuing transaction needs, in the one global order:
        the client row first (revoke_client locks it and then the client's token
        rows), then the family lock, then the user row FOR SHARE (a disable waits
        for this issue, so its revoke-all sees the new pair), and only then token
        or code rows. A disable takes no client or family lock, so there is no
        cycle. Returns the time after the waits, so a lock wait never stretches a
        window such as the refresh grace."""
        await self._creds.clients.touch_client(family.client_id, self._clock())
        await self._creds.families.lock_family(family.family_id)
        await self._users.lock_user(family.user_id)
        return self._clock()

    async def db_errors_as_unavailable(
        self, issuing: Awaitable[TokenPair], *, op: str
    ) -> TokenPair:
        """An unexpected database error (a deadlock, a lost connection, a pool
        timeout) becomes GrantUnavailableError: never a raw error with SQL in it,
        and never invalid_grant for a grant that is still good."""
        try:
            return await issuing
        except SQLAlchemyError as exc:
            await self.database_error(exc, op=op)
            raise GrantUnavailableError from None

    async def database_error(self, exc: SQLAlchemyError, *, op: str) -> None:
        """Logs a database error by type and operation only (the statement may
        carry hashes) and leaves the session usable."""
        logger.error("oauth.database_error", op=op, error=type(exc).__name__)
        with suppress(SQLAlchemyError):
            await self._creds.rollback()

    async def _issue_denial(
        self, family: Family, audience: str, eligible: Eligibility
    ) -> str | None:
        """Why tokens may not be issued now (a revoke reason), or None. The user is
        re-read (not taken from the session's identity map): this runs after
        lock_user, and a status read before it could be stale."""
        user = await self._users.get(family.user_id, fresh=True)
        if (
            user is None
            or user.status != UserStatus.ACTIVE
            or user.kind != UserKind.HUMAN
        ):
            return REVOKED_USER_DISABLED
        if await self._clients.get_client(family.client_id) is None:
            return REVOKED_CLIENT
        if not same_audience(self._config.resource, audience):
            return REVOKED_AUDIENCE_CHANGED
        if not await _is_eligible(eligible, family.user_id):
            return REVOKED_NO_MCP_USE
        return None

    async def checked_denial(
        self, family: Family, audience: str, eligible: Eligibility
    ) -> str | None:
        """`_issue_denial`, except that a check which could not be made rolls back
        (no code spent, no token rotated) and raises GrantUnavailableError: fail
        closed, but never revoke a family on a transient error."""
        try:
            return await self._issue_denial(family, audience, eligible)
        except EligibilityUnavailableError:
            await self._creds.rollback()
            logger.warning(
                "oauth.eligibility_unavailable", family_id=str(family.family_id)
            )
            raise GrantUnavailableError from None

    async def issue_checked(
        self,
        family: Family,
        audience: str,
        eligible: Eligibility,
        now: datetime,
        event: str,
    ) -> TokenPair:
        """Issues a pair after the per-refresh checks; a failed check revokes the
        whole family with that reason."""
        denial = await self.checked_denial(family, audience, eligible)
        if denial is not None:
            await self._creds.rollback()
            await self.revoke(family, denial)
            raise OAuthGrantError(DEAD_REFRESH)
        return await self.issue_pair(family, now, event)

    async def issue_pair(self, family: Family, now: datetime, event: str) -> TokenPair:
        audience = self._config.resource
        access, access_raw = _mint_row(
            TokenKind.OAUTH_ACCESS, family, audience, now, self._config.access_ttl
        )
        refresh, refresh_raw = _mint_row(
            TokenKind.OAUTH_REFRESH, family, audience, now, self._config.refresh_ttl
        )
        self._creds.add(access)
        self._creds.add(refresh)
        self._creds.add(
            CredentialEvent(
                event=event,
                via="oauth",
                user_id=family.user_id,
                client_id=family.client_id,
                token_id=refresh.id,
                details={
                    "family_id": str(family.family_id),
                    "access_token_id": str(access.id),
                },
            )
        )
        await self._creds.commit()
        logger.info(event, family_id=str(family.family_id))
        return TokenPair(
            access_token=access_raw,
            refresh_token=refresh_raw,
            expires_in=int(self._config.access_ttl.total_seconds()),
            family_id=family.family_id,
            user_id=family.user_id,
        )

    async def revoke(
        self,
        family: Family,
        reason: str,
        *,
        kind: ReuseKind | None = None,
        extra_details: Mapping[str, str] | None = None,
    ) -> None:
        """Revokes every live row of the family (under the family lock, taken by the
        repository) and records why, then commits. The event's client_id is the
        family's client; `extra_details` adds forensics such as the presenter (ids,
        never secrets). A failed reuse revoke is logged as such before the database
        error propagates: a replayed credential whose family is still live is the
        alarm an operator needs."""
        family_id = str(family.family_id)
        forensics = dict(extra_details or {})
        if reason in _REUSE_REASONS:
            event = EVENT_REUSE_DETECTED
            details: dict[str, Any] = {"family_id": family_id, "kind": kind}
            logger.warning(
                EVENT_REUSE_DETECTED, family_id=family_id, kind=kind, **forensics
            )
        else:
            event = EVENT_FAMILY_REVOKED
            details = {"family_id": family_id, "reason": reason}
            logger.info(EVENT_FAMILY_REVOKED, family_id=family_id, reason=reason)
        try:
            await self._creds.families.revoke_family(
                family.family_id, reason, self._clock()
            )
            self._creds.add(
                CredentialEvent(
                    event=event,
                    via="oauth",
                    user_id=family.user_id,
                    client_id=family.client_id,
                    details=details | forensics,
                )
            )
            await self._creds.commit()
        except SQLAlchemyError as exc:
            if reason in _REUSE_REASONS:
                logger.error(
                    "oauth.reuse_revoke_failed",
                    family_id=family_id,
                    kind=kind,
                    error=type(exc).__name__,
                )
            raise

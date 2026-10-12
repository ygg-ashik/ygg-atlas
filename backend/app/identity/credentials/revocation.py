"""Revoking tokens (one, or all of a user's) and connected apps: the OAuth token
families a user has consented to, which can still refresh."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID

import structlog

from app.identity.api_tokens import (
    EVENT_FAMILY_REVOKED,
    EVENT_TOKEN_REVOKED,
    EVENT_TOKENS_REVOKED_ALL,
    UNNAMED_CLIENT,
    CredentialActor,
)
from app.identity.clock import as_utc
from app.identity.credentials.events import EventStamper
from app.identity.errors import CredentialNotFoundError
from app.identity.repository import CredentialRepository, UserRepository

logger = structlog.get_logger()

_NO_TOKEN: Final = "No such token."  # noqa: S105  # a message, not a secret


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


def _redirect_host(uris: tuple[str, ...]) -> str:
    return (urlsplit(uris[0]).hostname or "") if uris else ""


class TokenRevoker:
    """Revokes tokens and token families, each with its credential_events row."""

    def __init__(
        self,
        creds: CredentialRepository,
        users: UserRepository,
        clock: Callable[[], datetime],
    ) -> None:
        self._creds = creds
        self._users = users
        self._clock = clock
        self._events = EventStamper(clock)

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
        token = await self._creds.tokens.token(token_id, fresh=True)
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
        if not await self._creds.tokens.revoke_token(token.id, reason, self._clock()):
            return  # already revoked: nothing changed, nothing to log
        self._creds.add(
            self._events.event(
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
        count = await self._creds.tokens.revoke_user_tokens(user_id, reason, now)
        codes = await self._creds.codes.spend_user_codes(user_id, now)
        self._creds.add(
            self._events.event(
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
        rows = await self._creds.families.connected_apps(user_id, self._clock())
        return [
            ConnectedApp(
                family_id=row.family_id,
                client_id=row.client_id,
                client_name=row.client_name or UNNAMED_CLIENT,
                redirect_host=_redirect_host(row.redirect_uris),
                created_at=as_utc(row.created_at),
                last_used_at=None
                if row.last_used_at is None
                else as_utc(row.last_used_at),
                expires_at=as_utc(row.expires_at),
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
            apps = await self._creds.families.connected_apps(owner_id, self._clock())
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
        count = await self._creds.families.revoke_family(
            family_id, reason, self._clock()
        )
        if count == 0:
            await self._creds.commit()  # nothing staged; ends the family lock
            return
        self._creds.add(
            self._events.event(
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

"""Minting personal (PAT) and service tokens, and naming service accounts. Raw
secrets exist only in `IssuedToken.raw`, once, and are never logged, stored or
put in a repr."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

import structlog

from app.identity.api_tokens import (
    EVENT_TOKEN_CREATED,
    MAX_LIVE_PATS,
    MAX_TOKEN_DAYS,
    CredentialActor,
    TokenKind,
    display_prefix,
    hash_secret,
    mint,
)
from app.identity.credentials.events import EventStamper
from app.identity.errors import CredentialLimitError, CredentialRuleError
from app.identity.models import ApiToken, UserKind, UserStatus
from app.identity.repository import CredentialRepository, UserRepository

logger = structlog.get_logger()

SERVICE_ACCOUNT_DOMAIN: Final = "atlas.internal"
_SLUG_SEPARATORS: Final = re.compile(r"[^a-z0-9]+")
_SLUG_MIN, _SLUG_MAX = 3, 40
_NAME_MAX: Final = 100


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A freshly minted token: the stored row and the raw value, shown once (D3)."""

    token: ApiToken
    raw: str = field(repr=False)  # never logged or stored


@dataclass(frozen=True, slots=True)
class TokenRequest:
    """One PAT or service-token mint, validated by TokenIssuer.issue."""

    user_id: UUID
    kind: TokenKind
    name: str
    expires_in_days: int | None
    actor: CredentialActor
    default_days: int
    max_days: int


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


def _token_name(name: str) -> str:
    cleaned = name.strip()
    if not 1 <= len(cleaned) <= _NAME_MAX:
        msg = f"Name the token in 1-{_NAME_MAX} characters."
        raise CredentialRuleError(msg)
    return cleaned


def _lifetime(request: TokenRequest) -> timedelta:
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


class TokenIssuer:
    """Mints PATs and service tokens for active holders of the right kind."""

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

    async def issue(self, request: TokenRequest) -> IssuedToken:
        name = _token_name(request.name)
        lifetime = _lifetime(request)
        await self._require_holder(request.user_id, request.kind)
        now = self._clock()
        if (
            request.kind is TokenKind.PAT
            and await self._creds.tokens.count_live(request.user_id, request.kind, now)
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
            self._events.event(
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

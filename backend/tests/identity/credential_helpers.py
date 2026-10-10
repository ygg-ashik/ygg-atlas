"""Direct-to-database credential helpers for identity and MCP tests.

They skip the token and OAuth services on purpose, so a test can set up any row
state (expired, revoked, rotated, foreign client) in one line.
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.api_tokens import (
    DISPLAY_PREFIX_LENGTH,
    TokenKind,
    display_prefix,
    hash_secret,
    mint,
)
from app.identity.models import ApiToken, OAuthClient, User

LOOPBACK_REDIRECT = "http://localhost:35535/oauth/callback"
_LEAK_WINDOW = 16  # chars past the display prefix that must never appear


async def make_client(
    db: AsyncSession,
    *,
    client_id: str | None = None,
    redirect_uris: Sequence[str] = (LOOPBACK_REDIRECT,),
    secret_hash: str | None = None,
    revoked: bool = False,
    name: str | None = "Claude Code",
) -> OAuthClient:
    """A registered OAuth client (public unless `secret_hash` is given)."""
    client = OAuthClient(
        client_id=client_id or f"client-{uuid4()}",
        client_name=name,
        redirect_uris=list(redirect_uris),
        token_endpoint_auth_method="client_secret_post" if secret_hash else "none",
        client_secret_hash=secret_hash,
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        revoked_at=datetime.now(UTC) if revoked else None,
    )
    db.add(client)
    await db.commit()
    return client


async def insert_token(
    db: AsyncSession,
    user: User,
    kind: TokenKind,
    *,
    expires_in: timedelta = timedelta(days=1),
    family_id: UUID | None = None,
    client_id: str | None = None,
    revoked_reason: str | None = None,
    audience: str | None = None,
) -> tuple[ApiToken, str]:
    """Store a token row for `user` and return it with the raw value it hashed."""
    raw = mint(kind)
    now = datetime.now(UTC)
    row = ApiToken(
        user_id=user.id,
        kind=kind,
        token_hash=hash_secret(raw),
        prefix=display_prefix(raw),
        name=f"{kind} token",
        client_id=client_id,
        family_id=family_id,
        audience=audience,
        created_at=now,
        expires_at=now + expires_in,
        revoked_at=now if revoked_reason else None,
        revoked_reason=revoked_reason,
    )
    db.add(row)
    await db.commit()
    return row, raw


def assert_no_secret(secret: str, *haystacks: object) -> None:
    """Neither the secret nor the 16 chars past its display prefix occur anywhere."""
    window = secret[DISPLAY_PREFIX_LENGTH : DISPLAY_PREFIX_LENGTH + _LEAK_WINDOW]
    assert window, "assert_no_secret needs a real secret, not a short string"
    for haystack in haystacks:
        text = (
            haystack if isinstance(haystack, str) else json.dumps(haystack, default=str)
        )
        assert secret not in text
        assert window not in text

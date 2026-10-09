"""AtlasTokenVerifier: identity's bearer door as the SDK's TokenVerifier (D20, D28)."""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import uuid4

import pytest
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from pydantic import AnyHttpUrl
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import HTTPConnection
from starlette.types import Message, Receive, Scope, Send
from structlog.testing import capture_logs

from app.database import get_session_factory
from app.identity import REVOKED_BY_USER, TokenKind, User
from app.identity.api_tokens import mint
from app.mcp.auth import (
    AtlasTokenVerifier,
    BearerRejectionScope,
    bearer_unrecognised,
    last_bearer_rejection,
)
from tests.access_helpers import make_user
from tests.identity.credential_helpers import (
    assert_no_secret,
    insert_token,
    make_client,
)
from tests.mcp.oauth_client import RESOURCE


async def _user(db: AsyncSession, *, status: str = "active") -> User:
    return await make_user(
        db, f"u-{uuid4().hex[:8]}@yougotagift.com", role="analyst", status=status
    )


def _connection(raw: str) -> HTTPConnection:
    return HTTPConnection(
        {"type": "http", "headers": [(b"authorization", f"Bearer {raw}".encode())]}
    )


async def test_pat_becomes_an_atlas_access_token(db) -> None:
    user = await _user(db)
    row, raw = await insert_token(db, user, TokenKind.PAT)

    token = await AtlasTokenVerifier(RESOURCE).verify_token(raw)

    assert token is not None
    assert token.token == raw[:14] == row.prefix
    assert token.client_id == "pat"
    assert token.resource == RESOURCE  # PATs follow the current URL (D7)
    assert token.subject == str(user.id)
    assert token.scopes == []
    assert token.principal.user_id == user.id
    assert token.token_id == row.id
    assert token.expires_at == int(row.expires_at.timestamp())
    assert last_bearer_rejection() is None


async def test_oauth_token_reports_its_bound_audience(db) -> None:
    user = await _user(db)
    client = await make_client(db)
    other = "https://elsewhere.example.com/mcp-server/mcp"
    _, raw = await insert_token(
        db,
        user,
        TokenKind.OAUTH_ACCESS,
        client_id=client.client_id,
        family_id=uuid4(),
        audience=other,
    )

    token = await AtlasTokenVerifier(RESOURCE).verify_token(raw)

    assert token is not None
    assert token.client_id == client.client_id
    assert token.resource == other


async def test_audience_mismatch_is_refused_by_the_bearer_backend(db) -> None:
    user = await _user(db)
    client = await make_client(db)
    verifier = AtlasTokenVerifier(RESOURCE)
    backend = BearerAuthBackend(verifier, resource_server_url=AnyHttpUrl(RESOURCE))
    tokens: dict[str, str] = {}
    for audience in (RESOURCE, "https://elsewhere.example.com/mcp-server/mcp"):
        _, tokens[audience] = await insert_token(
            db,
            user,
            TokenKind.OAUTH_ACCESS,
            client_id=client.client_id,
            family_id=uuid4(),
            audience=audience,
        )

    accepted = await backend.authenticate(_connection(tokens[RESOURCE]))
    refused = [
        await backend.authenticate(_connection(raw))
        for audience, raw in tokens.items()
        if audience != RESOURCE
    ]

    assert accepted is not None
    assert refused == [None]


async def _unknown(db: AsyncSession) -> str:
    return mint(TokenKind.PAT)


async def _revoked(db: AsyncSession) -> str:
    _, raw = await insert_token(
        db, await _user(db), TokenKind.PAT, revoked_reason=REVOKED_BY_USER
    )
    return raw


async def _malformed(db: AsyncSession) -> str:
    return "not-an-atlas-token-at-all-0123456789"


async def _refresh_kind(db: AsyncSession) -> str:
    client = await make_client(db)
    _, raw = await insert_token(
        db,
        await _user(db),
        TokenKind.OAUTH_REFRESH,
        client_id=client.client_id,
        family_id=uuid4(),
        audience=RESOURCE,
    )
    return raw


@pytest.mark.parametrize(
    "make_raw",
    [_unknown, _revoked, _malformed, _refresh_kind],
    ids=lambda f: f.__name__,
)
async def test_unrecognised_tokens_are_none(
    db, make_raw: Callable[[AsyncSession], Awaitable[str]]
) -> None:
    raw = await make_raw(db)

    with capture_logs() as logs:
        token = await AtlasTokenVerifier(RESOURCE).verify_token(raw)

    assert token is None
    assert last_bearer_rejection() == "unrecognised"
    if len(raw) >= 30:
        assert_no_secret(raw, logs)


async def test_expired_token_is_none_and_not_counted_as_guessing(db) -> None:
    """E1: a real token past its expiry is a client that must re-authenticate, not
    a guess, so the failed-bearer limiter must not count it."""
    _, raw = await insert_token(
        db, await _user(db), TokenKind.PAT, expires_in=timedelta(seconds=-1)
    )

    with capture_logs() as logs:
        token = await AtlasTokenVerifier(RESOURCE).verify_token(raw)

    assert token is None
    assert last_bearer_rejection() == "expired"
    assert_no_secret(raw, logs)


async def test_expired_and_revoked_token_is_unrecognised(db) -> None:
    _, raw = await insert_token(
        db,
        await _user(db),
        TokenKind.PAT,
        expires_in=timedelta(seconds=-1),
        revoked_reason=REVOKED_BY_USER,
    )

    assert await AtlasTokenVerifier(RESOURCE).verify_token(raw) is None
    assert last_bearer_rejection() == "unrecognised"


async def test_a_passing_check_clears_the_last_rejection(db) -> None:
    _, raw = await insert_token(db, await _user(db), TokenKind.PAT)
    verifier = AtlasTokenVerifier(RESOURCE)

    assert await verifier.verify_token(mint(TokenKind.PAT)) is None
    assert last_bearer_rejection() == "unrecognised"
    assert await verifier.verify_token(raw) is not None
    assert last_bearer_rejection() is None


async def test_disabled_owner_is_none_and_not_counted_as_guessing(db) -> None:
    user = await _user(db, status="disabled")
    _, raw = await insert_token(db, user, TokenKind.PAT)

    with capture_logs() as logs:
        assert await AtlasTokenVerifier(RESOURCE).verify_token(raw) is None
    assert last_bearer_rejection() == "refused"
    assert not bearer_unrecognised()
    # A clean rejection: no error-level failure log for a disabled owner.
    assert not [e for e in logs if e["log_level"] == "error"]
    assert {"event": "mcp.bearer_refused", "reason": "user_disabled"}.items() <= (
        logs[-1].items()
    )
    assert_no_secret(raw, logs)


async def test_verifier_fails_closed_on_unexpected_errors(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, raw = await insert_token(db, await _user(db), TokenKind.PAT)

    async def broken(_db: AsyncSession, token: str) -> None:
        raise RuntimeError(f"database exploded holding {token}")

    monkeypatch.setattr("app.mcp.auth.authenticate_bearer", broken)
    with capture_logs() as logs:
        token = await AtlasTokenVerifier(RESOURCE).verify_token(raw)

    assert token is None
    assert last_bearer_rejection() == "unavailable"
    assert {"event": "mcp.bearer_check_failed", "error": "RuntimeError"}.items() <= (
        logs[-1].items()
    )
    assert_no_secret(raw, logs)


async def test_access_token_repr_and_json_hold_no_secret(db) -> None:
    _, raw = await insert_token(db, await _user(db), TokenKind.PAT)

    token = await AtlasTokenVerifier(RESOURCE).verify_token(raw)

    assert token is not None
    assert_no_secret(raw, repr(token), str(token), token.model_dump_json())


async def test_each_check_runs_on_a_fresh_session(db) -> None:
    """The door commits last_used_at, and a reused session would serve a stale
    row from its identity map: a revoke made elsewhere must be seen at once."""
    row, raw = await insert_token(db, await _user(db), TokenKind.PAT)
    opened: list[int] = []

    def sessions() -> async_sessionmaker[AsyncSession]:
        opened.append(1)
        return get_session_factory()

    verifier = AtlasTokenVerifier(RESOURCE, sessions)
    assert await verifier.verify_token(raw) is not None

    async with get_session_factory()() as other:
        stored = await other.get(type(row), row.id)
        assert stored is not None
        stored.revoked_at = stored.created_at
        stored.revoked_reason = REVOKED_BY_USER
        await other.commit()

    assert await verifier.verify_token(raw) is None
    assert len(opened) == 2


async def test_rejection_scope_keeps_a_verdict_inside_its_request(db) -> None:
    """Two requests in one task: a bad bearer, then none. The second never sees
    the first's verdict, and nothing leaks past either request (ruling E1)."""
    verifier = AtlasTokenVerifier(RESOURCE)
    seen: list[str | None] = []

    async def bad_bearer(scope: Scope, receive: Receive, send: Send) -> None:
        await verifier.verify_token(mint(TokenKind.PAT))
        seen.append(last_bearer_rejection())

    async def no_bearer(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(last_bearer_rejection())

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message: Message) -> None:
        return None

    scope: Scope = {"type": "http", "headers": []}
    await BearerRejectionScope(bad_bearer)(scope, receive, send)
    assert last_bearer_rejection() is None
    await BearerRejectionScope(no_bearer)(scope, receive, send)

    assert seen == ["unrecognised", None]
    assert last_bearer_rejection() is None


async def test_rejection_scope_clears_a_stale_verdict(db) -> None:
    await AtlasTokenVerifier(RESOURCE).verify_token("garbage")
    assert bearer_unrecognised()
    seen: list[str | None] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(last_bearer_rejection())

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message: Message) -> None:
        return None

    await BearerRejectionScope(inner)({"type": "http", "headers": []}, receive, send)
    assert seen == [None]

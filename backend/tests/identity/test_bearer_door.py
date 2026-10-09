"""The single bearer door (D3, D20): prefix, kind, hash, liveness, owner and client.

Every rejection reads "invalid token" (or the disabled-user text) and never carries
token material; the reason goes to a structured log field.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from app.identity.api_tokens import (
    REVOKED_BY_USER,
    TOKEN_PREFIXES,
    TokenKind,
    mint,
)
from app.identity.credentials import authenticate_bearer, principal_for_user
from app.identity.errors import ForbiddenError
from app.identity.models import ApiToken, User
from app.identity.repository import CredentialRepository
from app.identity.tokens import InvalidTokenError
from tests.access_helpers import make_user
from tests.identity.credential_helpers import (
    assert_no_secret,
    insert_token,
    make_client,
)

RESOURCE = "http://localhost:8080/mcp-server/mcp"
DISABLED_TEXT = "Your atlas access is disabled. Contact an admin."


async def _human(db: AsyncSession, *, status: str = "active") -> User:
    return await make_user(db, f"u-{uuid4().hex[:8]}@yougotagift.com", status=status)


async def _service(db: AsyncSession, *, status: str = "active") -> User:
    return await make_user(
        db, f"svc-{uuid4().hex[:8]}@atlas.internal", kind="service", status=status
    )


async def _reload(db: AsyncSession, token: ApiToken) -> ApiToken:
    row = await CredentialRepository(db).token(token.id, fresh=True)
    assert row is not None
    return row


async def test_pat_authenticates_as_pat(db) -> None:
    user = await _human(db)
    row, raw = await insert_token(db, user, TokenKind.PAT)

    bearer = await authenticate_bearer(db, raw)

    assert bearer.principal.user_id == user.id
    assert bearer.principal.auth_method == "pat"
    assert bearer.principal.token_id == row.id
    assert bearer.principal.client_id is None
    assert bearer.audience is None
    assert bearer.display_prefix == raw[:14]
    assert bearer.expires_at.tzinfo is not None


async def test_service_token_requires_a_service_user(db) -> None:
    service = await _service(db)
    _, raw = await insert_token(db, service, TokenKind.SERVICE)
    bearer = await authenticate_bearer(db, raw)
    assert bearer.principal.auth_method == "service"
    assert bearer.principal.kind == "service"

    human = await _human(db)
    _, wrong = await insert_token(db, human, TokenKind.SERVICE)
    with pytest.raises(InvalidTokenError, match=r"^invalid token$"):
        await authenticate_bearer(db, wrong)


async def test_pat_refuses_a_service_user(db) -> None:
    service = await _service(db)
    _, raw = await insert_token(db, service, TokenKind.PAT)
    with pytest.raises(InvalidTokenError, match=r"^invalid token$"):
        await authenticate_bearer(db, raw)


async def test_oauth_access_token_carries_client_and_audience(db) -> None:
    user = await _human(db)
    client = await make_client(db)
    row, raw = await insert_token(
        db,
        user,
        TokenKind.OAUTH_ACCESS,
        client_id=client.client_id,
        family_id=uuid4(),
        audience=RESOURCE,
    )

    bearer = await authenticate_bearer(db, raw)

    assert bearer.principal.auth_method == "oauth"
    assert bearer.principal.token_id == row.id
    assert bearer.principal.client_id == client.client_id
    assert bearer.audience == RESOURCE


async def test_oauth_access_token_on_a_service_user_is_refused(db) -> None:
    service = await _service(db)
    client = await make_client(db)
    _, raw = await insert_token(
        db, service, TokenKind.OAUTH_ACCESS, client_id=client.client_id
    )
    with pytest.raises(InvalidTokenError, match=r"^invalid token$"):
        await authenticate_bearer(db, raw)


async def test_refresh_token_is_never_a_bearer(db) -> None:
    user = await _human(db)
    client = await make_client(db)
    _, raw = await insert_token(
        db, user, TokenKind.OAUTH_REFRESH, client_id=client.client_id
    )
    with pytest.raises(InvalidTokenError, match=r"^invalid token$"):
        await authenticate_bearer(db, raw)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not-a-token",
        "eyJhbGciOiJSUzI1NiJ9.e30.sig",
        "atl_xyz_" + "a" * 43,
        "atl_pat_short",
        "atl_pat_" + "a" * 44,
        "atl_pat_" + "a" * 42 + "!",
        TOKEN_PREFIXES[TokenKind.OAUTH_REFRESH] + "r" * 43,  # well formed, not a bearer
    ],
    ids=[
        "empty",
        "plain",
        "jwt",
        "unknown-prefix",
        "short-body",
        "long-body",
        "bad-char",
        "refresh",
    ],
)
async def test_unknown_prefix_is_rejected_without_a_query(
    db, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    async def _no_lookup(self: CredentialRepository, token_hash: str) -> None:
        raise AssertionError("token_by_hash must not run for a malformed bearer")

    monkeypatch.setattr(CredentialRepository, "token_by_hash", _no_lookup)
    with pytest.raises(InvalidTokenError, match=r"^invalid token$"):
        await authenticate_bearer(db, raw)


async def test_unknown_well_formed_token_is_rejected(db) -> None:
    with pytest.raises(InvalidTokenError, match=r"^invalid token$"):
        await authenticate_bearer(db, mint(TokenKind.PAT))


async def test_expired_token_is_rejected(db) -> None:
    user = await _human(db)
    _, raw = await insert_token(db, user, TokenKind.PAT, expires_in=timedelta(days=1))
    with pytest.raises(InvalidTokenError, match=r"^invalid token$"):
        await authenticate_bearer(db, raw, now=datetime.now(UTC) + timedelta(days=2))


async def test_token_expiring_exactly_now_is_rejected(db) -> None:
    user = await _human(db)
    row, raw = await insert_token(db, user, TokenKind.PAT)
    expires_at = row.expires_at
    moment = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
    with pytest.raises(InvalidTokenError, match=r"^invalid token$"):
        await authenticate_bearer(db, raw, now=moment)
    accepted = await authenticate_bearer(db, raw, now=moment - timedelta(seconds=1))
    assert accepted.principal.token_id == row.id


async def test_revoked_token_is_rejected(db) -> None:
    user = await _human(db)
    _, raw = await insert_token(db, user, TokenKind.PAT, revoked_reason=REVOKED_BY_USER)
    with pytest.raises(InvalidTokenError, match=r"^invalid token$"):
        await authenticate_bearer(db, raw)


async def test_kind_mismatch_is_rejected(db) -> None:
    user = await _human(db)
    row, raw = await insert_token(db, user, TokenKind.PAT)
    row.kind = TokenKind.SERVICE  # a PAT hash stored as a service token
    db.add(row)
    await db.commit()
    with pytest.raises(InvalidTokenError, match=r"^invalid token$"):
        await authenticate_bearer(db, raw)


async def test_disabled_user_is_forbidden(db) -> None:
    user = await _human(db, status="disabled")
    _, raw = await insert_token(db, user, TokenKind.PAT)
    with pytest.raises(ForbiddenError) as caught:
        await authenticate_bearer(db, raw)
    assert str(caught.value) == DISABLED_TEXT


async def test_disabled_service_account_is_forbidden(db) -> None:
    service = await _service(db, status="disabled")
    _, raw = await insert_token(db, service, TokenKind.SERVICE)
    with pytest.raises(ForbiddenError):
        await authenticate_bearer(db, raw)


async def test_revoked_client_kills_its_access_tokens(db) -> None:
    user = await _human(db)
    client = await make_client(db, revoked=True)
    _, raw = await insert_token(
        db, user, TokenKind.OAUTH_ACCESS, client_id=client.client_id
    )
    with pytest.raises(InvalidTokenError, match=r"^invalid token$"):
        await authenticate_bearer(db, raw)


async def test_access_token_without_a_client_is_rejected(db) -> None:
    user = await _human(db)
    _, raw = await insert_token(db, user, TokenKind.OAUTH_ACCESS)
    with pytest.raises(InvalidTokenError, match=r"^invalid token$"):
        await authenticate_bearer(db, raw)


async def test_last_used_is_written_at_most_every_five_minutes(db) -> None:
    user = await _human(db)
    row, raw = await insert_token(db, user, TokenKind.PAT)
    start = datetime.now(UTC)

    await authenticate_bearer(db, raw, now=start)
    first = (await _reload(db, row)).last_used_at
    assert first is not None
    assert first.replace(tzinfo=UTC) == start

    await authenticate_bearer(db, raw, now=start + timedelta(minutes=4))
    assert (await _reload(db, row)).last_used_at == first

    later = start + timedelta(minutes=5, seconds=1)
    await authenticate_bearer(db, raw, now=later)
    touched = (await _reload(db, row)).last_used_at
    assert touched is not None
    assert touched.replace(tzinfo=UTC) == later


async def test_whitespace_around_the_token_is_ignored(db) -> None:
    user = await _human(db)
    _, raw = await insert_token(db, user, TokenKind.PAT)
    bearer = await authenticate_bearer(db, f"  {raw}\n")
    assert bearer.principal.user_id == user.id


async def test_rejections_never_echo_the_token(db) -> None:
    user = await _human(db)
    disabled = await _human(db, status="disabled")
    revoked_client = await make_client(db, revoked=True)
    _, revoked = await insert_token(
        db, user, TokenKind.PAT, revoked_reason=REVOKED_BY_USER
    )
    _, expired = await insert_token(
        db, user, TokenKind.PAT, expires_in=timedelta(seconds=-1)
    )
    _, refresh = await insert_token(db, user, TokenKind.OAUTH_REFRESH)
    _, dead_client = await insert_token(
        db, user, TokenKind.OAUTH_ACCESS, client_id=revoked_client.client_id
    )
    _, forbidden = await insert_token(db, disabled, TokenKind.PAT)
    raws = [
        revoked,
        expired,
        refresh,
        dead_client,
        forbidden,
        mint(TokenKind.PAT),  # unknown
        TOKEN_PREFIXES[TokenKind.PAT] + "x" * 50,  # malformed body
    ]
    for raw in raws:
        with (
            capture_logs() as logs,
            pytest.raises((InvalidTokenError, ForbiddenError)) as caught,
        ):
            await authenticate_bearer(db, raw)
        assert str(caught.value) in {"invalid token", DISABLED_TEXT}
        assert logs, "every rejection is logged with its reason"
        assert all("reason" in entry for entry in logs)
        if len(raw) >= 30:
            assert_no_secret(raw, str(caught.value), repr(caught.value), logs)
        else:
            assert raw not in str(logs)


async def test_principal_for_user_maps_kind_and_refuses_inactive_users(db) -> None:
    human = await _human(db)
    service = await _service(db)
    disabled = await _human(db, status="disabled")

    as_human = await principal_for_user(db, human.id)
    as_service = await principal_for_user(db, service.id)

    assert as_human is not None
    assert as_human.auth_method == "pat"
    assert as_service is not None
    assert as_service.auth_method == "service"
    assert await principal_for_user(db, disabled.id) is None
    assert await principal_for_user(db, uuid4()) is None

"""The credentials CLI (Task 9): PATs and service tokens minted on the box, shown once,
audited via="cli"; listing never prints secrets; clients and gc for operators."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select
from structlog.testing import capture_logs

from app.access.models import RbacChange
from app.identity import REVOKED_BY_ADMIN, UserKind
from app.identity.api_tokens import (
    EVENT_CLIENT_REVOKED,
    EVENT_TOKEN_CREATED,
    EVENT_TOKEN_REVOKED,
    EVENT_TOKENS_REVOKED_ALL,
    TokenKind,
    hash_secret,
    kind_of,
)
from app.identity.models import (
    ApiToken,
    CredentialEvent,
    OAuthAuthorizationRequest,
    OAuthClient,
    User,
)
from app.mcp import cli
from tests.access_helpers import make_user
from tests.identity.credential_helpers import (
    assert_no_secret,
    insert_token,
    make_client,
)

HUMAN = "pat-owner@yougotagift.com"
STORE_NOTICE = "won't be shown again"


async def _token_row(db: AsyncSession, raw: str) -> ApiToken:
    stmt = (
        select(ApiToken)
        .where(col(ApiToken.token_hash) == hash_secret(raw))
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _events(db: AsyncSession, event: str) -> list[CredentialEvent]:
    stmt = (
        select(CredentialEvent)
        .where(col(CredentialEvent.event) == event)
        .execution_options(populate_existing=True)
    )
    return list((await db.execute(stmt)).scalars().all())


def _last_line(text: str) -> str:
    return text.strip().splitlines()[-1]


# ---- create-pat ---------------------------------------------------------------------


async def test_create_pat_prints_the_token_once_and_stores_its_hash(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    await make_user(db, HUMAN)

    code = await cli.run(["create-pat", HUMAN, "--name", "laptop", "--days", "30"])

    captured = capsys.readouterr()
    assert code == 0
    raw = _last_line(captured.out)
    assert kind_of(raw) is TokenKind.PAT
    assert captured.out.count(raw) == 1
    assert raw not in captured.err
    assert STORE_NOTICE in captured.err
    row = await _token_row(db, raw)
    assert row.name == "laptop"
    assert row.kind == TokenKind.PAT
    assert f"id: {row.id}" in captured.out
    assert f"prefix: {row.prefix}" in captured.out
    assert "expires_at: " in captured.out
    lifetime = row.expires_at.replace(tzinfo=UTC) - datetime.now(UTC)
    assert timedelta(days=29) < lifetime <= timedelta(days=30)


async def test_create_pat_never_logs_or_audits_the_raw_token(
    db: AsyncSession,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await make_user(db, HUMAN)
    caplog.set_level(logging.DEBUG)

    with capture_logs() as events:
        assert await cli.run(["create-pat", HUMAN]) == 0

    captured = capsys.readouterr()
    raw = _last_line(captured.out)
    assert events, "the mint is expected to log (without the secret)"
    audit = [e.details for e in await _events(db, EVENT_TOKEN_CREATED)]
    assert_no_secret(raw, events, caplog.text, captured.err, audit)


async def test_create_pat_is_audited_via_cli(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    user = await make_user(db, HUMAN)

    assert await cli.run(["create-pat", HUMAN, "--name", "ci"]) == 0

    raw = _last_line(capsys.readouterr().out)
    row = await _token_row(db, raw)
    (event,) = await _events(db, EVENT_TOKEN_CREATED)
    assert event.via == "cli"
    assert event.actor_user_id is None
    assert event.user_id == user.id
    assert event.token_id == row.id
    assert row.created_by is None


@pytest.mark.parametrize(
    ("status", "kind"),
    [("disabled", "human"), ("active", "service")],
)
async def test_create_pat_refuses_disabled_or_service_users(
    db: AsyncSession,
    capsys: pytest.CaptureFixture[str],
    status: str,
    kind: str,
) -> None:
    await make_user(db, HUMAN, status=status, kind=kind)

    assert await cli.run(["create-pat", HUMAN]) == 1

    captured = capsys.readouterr()
    assert "atl_" not in captured.out + captured.err
    assert "Personal tokens are for active people only." in captured.err
    assert await _events(db, EVENT_TOKEN_CREATED) == []


async def test_create_pat_refuses_unknown_users(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await cli.run(["create-pat", "ghost@yougotagift.com"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "No user ghost@yougotagift.com" in captured.err


async def test_unknown_user_message_strips_terminal_control_codes(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await cli.run(["create-pat", "evil\x1b[2J@yougotagift.com"]) == 1

    captured = capsys.readouterr()
    assert "\x1b" not in captured.err
    assert "No user evil?[2J@yougotagift.com" in captured.err


async def test_create_pat_rejects_a_lifetime_over_the_maximum(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    await make_user(db, HUMAN)

    assert await cli.run(["create-pat", HUMAN, "--days", "9999"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "A token lasts 1-365 days." in captured.err


# ---- service accounts -------------------------------------------------------------


async def test_create_service_account_then_token(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    email = "svc-nightly-etl@atlas.internal"

    assert (
        await cli.run(["create-service-account", "Nightly ETL", "--role", "analyst"])
        == 0
    )
    assert email in capsys.readouterr().out
    account = (
        await db.execute(select(User).where(col(User.email) == email))
    ).scalar_one()
    assert account.kind == UserKind.SERVICE
    assert account.role == "analyst"
    change = (
        await db.execute(
            select(RbacChange).where(col(RbacChange.action) == "service_account.create")
        )
    ).scalar_one()
    assert change.via == "cli"

    with capture_logs() as events:
        code = await cli.run(["create-service-token", email, "--name", "etl"])

    captured = capsys.readouterr()
    assert code == 0
    raw = _last_line(captured.out)
    assert kind_of(raw) is TokenKind.SERVICE
    assert captured.out.count(raw) == 1
    assert STORE_NOTICE in captured.err
    row = await _token_row(db, raw)
    assert row.user_id == account.id
    (event,) = await _events(db, EVENT_TOKEN_CREATED)
    assert event.via == "cli"
    assert_no_secret(raw, events, captured.err, event.details)


async def test_create_service_account_rejects_a_bad_role(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await cli.run(["create-service-account", "etl-job", "--role", "god"]) == 1
    assert "Unknown role 'god'" in capsys.readouterr().err


async def test_create_service_token_refuses_a_human(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    await make_user(db, HUMAN)

    assert await cli.run(["create-service-token", HUMAN]) == 1

    captured = capsys.readouterr()
    assert "atl_" not in captured.out
    assert "Service tokens need an active service account." in captured.err


# ---- list-tokens ---------------------------------------------------------------------


async def test_list_tokens_never_prints_secrets(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    owner = await make_user(db, HUMAN)
    other = await make_user(db, "other@yougotagift.com")
    pat, pat_raw = await insert_token(db, owner, TokenKind.PAT)
    other_pat, other_raw = await insert_token(db, other, TokenKind.PAT)
    client = await make_client(db)
    oauth, oauth_raw = await insert_token(
        db, owner, TokenKind.OAUTH_ACCESS, client_id=client.client_id
    )

    assert await cli.run(["list-tokens"]) == 0
    everything = capsys.readouterr().out
    assert str(pat.id) in everything
    assert pat.prefix in everything
    assert HUMAN in everything
    assert str(other_pat.id) in everything
    assert str(oauth.id) not in everything  # oauth tokens only on request

    assert await cli.run(["list-tokens", "--email", HUMAN]) == 0
    mine = capsys.readouterr().out
    assert str(pat.id) in mine
    assert str(other_pat.id) not in mine

    assert await cli.run(["list-tokens", "--kind", "oauth"]) == 0
    oauth_only = capsys.readouterr().out
    assert str(oauth.id) in oauth_only
    assert str(pat.id) not in oauth_only

    for raw in (pat_raw, other_raw, oauth_raw):
        assert_no_secret(raw, everything, mine, oauth_only)


async def test_list_tokens_says_when_there_are_none(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await cli.run(["list-tokens"]) == 0
    assert "no tokens" in capsys.readouterr().out


# ---- revoke-token / revoke-all -------------------------------------------------------


async def test_revoke_token(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    owner = await make_user(db, HUMAN)
    token, raw = await insert_token(db, owner, TokenKind.PAT)
    token_id = token.id

    assert await cli.run(["revoke-token", str(token_id)]) == 0

    assert f"revoked {token_id}" in capsys.readouterr().out
    row = await _token_row(db, raw)
    assert row.revoked_at is not None
    assert row.revoked_reason == REVOKED_BY_ADMIN
    (event,) = await _events(db, EVENT_TOKEN_REVOKED)
    assert event.via == "cli"
    assert event.actor_user_id is None


async def test_revoke_token_with_a_reason(db: AsyncSession) -> None:
    owner = await make_user(db, HUMAN)
    token, raw = await insert_token(db, owner, TokenKind.PAT)

    assert (
        await cli.run(["revoke-token", str(token.id), "--reason", "leaked_in_ci"]) == 0
    )

    assert (await _token_row(db, raw)).revoked_reason == "leaked_in_ci"


async def test_revoke_token_reports_unknown_and_malformed_ids(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await cli.run(["revoke-token", str(uuid4())]) == 1
    assert "No such token." in capsys.readouterr().err
    assert await cli.run(["revoke-token", "not-a-uuid"]) == 1
    assert "error:" in capsys.readouterr().err


async def test_revoke_all(db: AsyncSession, capsys: pytest.CaptureFixture[str]) -> None:
    owner = await make_user(db, HUMAN)
    _, first = await insert_token(db, owner, TokenKind.PAT)
    _, second = await insert_token(db, owner, TokenKind.PAT)

    assert await cli.run(["revoke-all", HUMAN]) == 0

    assert "revoked 2 tokens" in capsys.readouterr().out
    for raw in (first, second):
        assert (await _token_row(db, raw)).revoked_reason == REVOKED_BY_ADMIN
    (event,) = await _events(db, EVENT_TOKENS_REVOKED_ALL)
    assert event.via == "cli"
    assert event.user_id == owner.id


# ---- clients and gc ------------------------------------------------------------------


async def test_list_and_revoke_clients(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    owner = await make_user(db, HUMAN)
    client = await make_client(db, name="Claude Code")
    client_id = client.client_id
    _, raw = await insert_token(db, owner, TokenKind.OAUTH_ACCESS, client_id=client_id)

    assert await cli.run(["list-clients"]) == 0
    listing = capsys.readouterr().out
    assert client_id in listing
    assert "Claude Code" in listing

    assert await cli.run(["revoke-client", client_id]) == 0
    assert f"revoked client {client_id}" in capsys.readouterr().out
    stored = (
        await db.execute(
            select(OAuthClient)
            .where(col(OAuthClient.client_id) == client_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert stored.revoked_at is not None
    assert (await _token_row(db, raw)).revoked_at is not None
    (event,) = await _events(db, EVENT_CLIENT_REVOKED)
    assert event.via == "cli"

    assert await cli.run(["revoke-client", client_id]) == 1
    assert "No active client" in capsys.readouterr().err


async def test_list_clients_says_when_there_are_none(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await cli.run(["list-clients"]) == 0
    assert "no clients" in capsys.readouterr().out


async def test_gc_prints_counts(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    client = await make_client(db)
    db.add(
        OAuthAuthorizationRequest(
            id=hash_secret("stale-txn"),
            client_id=client.client_id,
            redirect_uri="http://localhost:35535/oauth/callback",
            redirect_uri_provided_explicitly=True,
            code_challenge="x" * 43,
            scopes=[],
            resource="http://localhost:8080/mcp-server/mcp",
            created_at=datetime.now(UTC) - timedelta(days=2),
            expires_at=datetime.now(UTC) - timedelta(days=2),
        )
    )
    await db.commit()

    assert await cli.run(["gc"]) == 0

    out = capsys.readouterr().out
    assert "requests: 1" in out
    for label in ("codes:", "tokens:", "clients:"):
        assert label in out


# ---- usage ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["create-pat"],
        ["create-pat", HUMAN, "--days", "soon"],
        ["create-service-account", "etl"],
        ["list-tokens", "--kind", "refresh"],
        ["revoke-token", "x", "--reason", "Not A Reason!"],
        ["no-such-command"],
    ],
)
async def test_usage_errors_exit_2(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        await cli.run(argv)
    assert exit_info.value.code == 2
    assert capsys.readouterr().out == ""

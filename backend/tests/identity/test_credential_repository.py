"""CredentialRepository: reads return rows; every "only once" write is one
conditional UPDATE whose rowcount decides (D5, D6)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.api_tokens import (
    REVOKED_APP_DISCONNECTED,
    REVOKED_BY_USER,
    REVOKED_CLIENT,
    REVOKED_CODE_REUSE,
    REVOKED_ROTATED,
    REVOKED_USER_DISABLED,
    TokenKind,
    mint_secret,
)
from app.identity.models import (
    ApiToken,
    CredentialEvent,
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthCode,
    User,
)
from app.identity.repository import CredentialRepository
from tests.access_helpers import make_user
from tests.identity.credential_helpers import (
    LOOPBACK_REDIRECT,
    assert_no_secret,
    insert_token,
    make_client,
)

RESOURCE = "http://localhost:8080/mcp-server/mcp"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def _now() -> datetime:
    return datetime.now(UTC)


async def _code(
    db: AsyncSession, user: User, client: OAuthClient, *, expires_in: timedelta
) -> OAuthCode:
    now = _now()
    code = OAuthCode(
        code_hash=mint_secret(),  # any unique 64-char-or-less value stands in here
        client_id=client.client_id,
        user_id=user.id,
        family_id=uuid4(),
        code_challenge=CHALLENGE,
        redirect_uri=LOOPBACK_REDIRECT,
        redirect_uri_provided_explicitly=True,
        resource=RESOURCE,
        scopes=[],
        created_at=now,
        expires_at=now + expires_in,
    )
    db.add(code)
    await db.commit()
    return code


async def _request(
    db: AsyncSession, client: OAuthClient, *, expires_in: timedelta
) -> OAuthAuthorizationRequest:
    now = _now()
    request = OAuthAuthorizationRequest(
        id=mint_secret(),
        client_id=client.client_id,
        redirect_uri=LOOPBACK_REDIRECT,
        redirect_uri_provided_explicitly=True,
        code_challenge=CHALLENGE,
        state="s",
        scopes=[],
        resource=RESOURCE,
        created_at=now,
        expires_at=now + expires_in,
    )
    db.add(request)
    await db.commit()
    return request


async def _reason(creds: CredentialRepository, row: ApiToken) -> str | None:
    fresh = await creds.token(row.id, fresh=True)
    assert fresh is not None
    return fresh.revoked_reason


async def test_token_hash_is_unique(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    row, _ = await insert_token(db, user, TokenKind.PAT)
    now = _now()
    db.add(
        ApiToken(
            user_id=user.id,
            kind=TokenKind.PAT,
            token_hash=row.token_hash,
            prefix="atl_pat_xxxxxx",
            created_at=now,
            expires_at=now + timedelta(days=1),
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_token_lookups(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    row, _ = await insert_token(db, user, TokenKind.PAT)
    creds = CredentialRepository(db)

    by_hash = await creds.token_by_hash(row.token_hash)
    assert by_hash is not None
    assert by_hash.id == row.id
    assert await creds.token_by_hash("0" * 64) is None
    fresh = await creds.token(row.id, fresh=True)
    assert fresh is not None
    assert fresh.id == row.id
    assert await creds.token(uuid4()) is None


async def test_mark_code_used_succeeds_once(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    client = await make_client(db)
    code = await _code(db, user, client, expires_in=timedelta(seconds=60))
    creds = CredentialRepository(db)

    assert await creds.mark_code_used(code.id, _now()) is True
    await creds.commit()
    assert await creds.mark_code_used(code.id, _now()) is False
    fresh = await creds.code(code.id, fresh=True)
    assert fresh is not None
    assert fresh.used_at is not None
    by_hash = await creds.code_by_hash(code.code_hash)
    assert by_hash is not None
    assert by_hash.id == code.id


async def test_mark_code_used_refuses_an_expired_code(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    client = await make_client(db)
    code = await _code(db, user, client, expires_in=timedelta(seconds=-1))

    assert await CredentialRepository(db).mark_code_used(code.id, _now()) is False


async def test_mark_rotated_succeeds_once(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    client = await make_client(db)
    row, _ = await insert_token(
        db, user, TokenKind.OAUTH_REFRESH, family_id=uuid4(), client_id=client.client_id
    )
    creds = CredentialRepository(db)

    assert await creds.mark_rotated(row.id, _now()) is True
    await creds.commit()
    assert await creds.mark_rotated(row.id, _now()) is False
    fresh = await creds.token(row.id, fresh=True)
    assert fresh is not None
    assert fresh.revoked_reason == REVOKED_ROTATED


async def test_consume_request_succeeds_once_and_never_after_expiry(db) -> None:
    client = await make_client(db)
    live = await _request(db, client, expires_in=timedelta(minutes=10))
    stale = await _request(db, client, expires_in=timedelta(seconds=-1))
    creds = CredentialRepository(db)

    assert await creds.pending_request(live.id, _now()) is not None
    consumed = await creds.consume_request(live.id, _now())
    assert consumed is not None
    assert consumed.consumed_at is not None
    await creds.commit()
    assert await creds.consume_request(live.id, _now()) is None
    assert await creds.pending_request(live.id, _now()) is None
    assert await creds.pending_request(stale.id, _now()) is None
    assert await creds.consume_request(stale.id, _now()) is None
    assert await creds.consume_request("missing", _now()) is None


async def test_revoke_family_keeps_earlier_reasons(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    client = await make_client(db)
    family = uuid4()
    rotated, _ = await insert_token(
        db,
        user,
        TokenKind.OAUTH_REFRESH,
        family_id=family,
        client_id=client.client_id,
        revoked_reason=REVOKED_ROTATED,
    )
    live, _ = await insert_token(
        db, user, TokenKind.OAUTH_ACCESS, family_id=family, client_id=client.client_id
    )
    other, _ = await insert_token(
        db, user, TokenKind.OAUTH_ACCESS, family_id=uuid4(), client_id=client.client_id
    )
    creds = CredentialRepository(db)

    assert await creds.revoke_family(family, REVOKED_CODE_REUSE, _now()) == 1
    await creds.commit()

    reasons = {r.id: await _reason(creds, r) for r in (rotated, live, other)}
    assert reasons == {
        rotated.id: REVOKED_ROTATED,
        live.id: REVOKED_CODE_REUSE,
        other.id: None,
    }


async def test_family_has_live_token(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    client = await make_client(db)
    family = uuid4()
    creds = CredentialRepository(db)
    assert await creds.family_has_live_token(family, _now()) is False

    await insert_token(
        db,
        user,
        TokenKind.OAUTH_REFRESH,
        family_id=family,
        client_id=client.client_id,
        revoked_reason=REVOKED_ROTATED,
    )
    await insert_token(
        db,
        user,
        TokenKind.OAUTH_ACCESS,
        family_id=family,
        client_id=client.client_id,
        expires_in=timedelta(seconds=-1),
    )
    assert await creds.family_has_live_token(family, _now()) is False

    await insert_token(
        db, user, TokenKind.OAUTH_REFRESH, family_id=family, client_id=client.client_id
    )
    assert await creds.family_has_live_token(family, _now()) is True


async def test_revoke_user_and_client_tokens(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    omar = await make_user(db, "omar@yougotagift.com")
    client = await make_client(db)
    pat, _ = await insert_token(db, sara, TokenKind.PAT)
    access, _ = await insert_token(
        db, sara, TokenKind.OAUTH_ACCESS, family_id=uuid4(), client_id=client.client_id
    )
    omars, _ = await insert_token(
        db, omar, TokenKind.OAUTH_ACCESS, family_id=uuid4(), client_id=client.client_id
    )
    creds = CredentialRepository(db)

    assert await creds.revoke_user_tokens(sara.id, REVOKED_USER_DISABLED, _now()) == 2
    assert await creds.revoke_user_tokens(sara.id, REVOKED_USER_DISABLED, _now()) == 0
    assert (
        await creds.revoke_client_tokens(client.client_id, REVOKED_CLIENT, _now()) == 1
    )
    assert await creds.revoke_client(client.client_id, _now()) is True
    assert await creds.revoke_client(client.client_id, _now()) is False
    await creds.commit()

    for row, reason in (
        (pat, REVOKED_USER_DISABLED),
        (access, REVOKED_USER_DISABLED),
        (omars, REVOKED_CLIENT),
    ):
        fresh = await creds.token(row.id, fresh=True)
        assert fresh is not None
        assert fresh.revoked_reason == reason
    revoked = await creds.client(client.client_id)
    assert revoked is not None
    assert revoked.revoked_at is not None


async def test_revoke_token_is_conditional(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    row, _ = await insert_token(db, user, TokenKind.PAT)
    creds = CredentialRepository(db)

    assert await creds.revoke_token(row.id, REVOKED_BY_USER, _now()) is True
    assert await creds.revoke_token(row.id, REVOKED_APP_DISCONNECTED, _now()) is False
    await creds.commit()
    fresh = await creds.token(row.id, fresh=True)
    assert fresh is not None
    assert fresh.revoked_reason == REVOKED_BY_USER


async def test_count_live_counts_only_live_tokens_of_the_kind(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    await insert_token(db, user, TokenKind.PAT)
    await insert_token(db, user, TokenKind.PAT, revoked_reason=REVOKED_BY_USER)
    await insert_token(db, user, TokenKind.PAT, expires_in=timedelta(seconds=-1))
    await insert_token(db, user, TokenKind.SERVICE)

    assert (
        await CredentialRepository(db).count_live(user.id, TokenKind.PAT, _now()) == 1
    )


async def test_touch_writes_last_used(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    client = await make_client(db)
    row, _ = await insert_token(db, user, TokenKind.PAT)
    creds = CredentialRepository(db)
    moment = _now()

    await creds.touch_token(row.id, moment)
    await creds.touch_client(client.client_id, moment)
    await creds.commit()

    token = await creds.token(row.id, fresh=True)
    touched = await creds.client(client.client_id)
    assert token is not None
    assert token.last_used_at is not None
    assert touched is not None
    await db.refresh(touched)
    assert touched.last_used_at is not None


async def test_list_tokens_is_tenant_scoped(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    other = await make_user(db, "eve@other.example")
    other.tenant = "other"
    db.add(other)
    await db.commit()
    pat, _ = await insert_token(db, sara, TokenKind.PAT)
    revoked, _ = await insert_token(
        db, sara, TokenKind.PAT, revoked_reason=REVOKED_BY_USER
    )
    await insert_token(db, sara, TokenKind.OAUTH_ACCESS)
    await insert_token(db, other, TokenKind.PAT)
    creds = CredentialRepository(db)

    ygg = await creds.list_tokens(tenant="ygg", kinds=[TokenKind.PAT])
    assert [t.id for t in ygg] == [pat.id]
    everything = await creds.list_tokens(
        tenant="ygg", kinds=[TokenKind.PAT], user_id=sara.id, include_revoked=True
    )
    assert {t.id for t in everything} == {pat.id, revoked.id}
    assert (
        await creds.list_tokens(tenant="ygg", kinds=[TokenKind.PAT], user_id=other.id)
        == []
    )
    assert len(await creds.list_tokens(tenant="other", kinds=[TokenKind.PAT])) == 1


async def test_list_events_is_tenant_scoped_and_newest_first(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    other = await make_user(db, "eve@other.example")
    other.tenant = "other"
    db.add(other)
    now = _now()
    db.add_all(
        [
            CredentialEvent(event="token.created", user_id=sara.id, via="api", at=now),
            CredentialEvent(
                event="token.revoked",
                user_id=sara.id,
                via="api",
                at=now + timedelta(seconds=1),
            ),
            CredentialEvent(event="token.created", user_id=other.id, via="api", at=now),
            CredentialEvent(event="credentials.gc", via="system", at=now),
        ]
    )
    await db.commit()
    creds = CredentialRepository(db)

    mine = await creds.list_events(tenant="ygg", user_id=sara.id)
    assert [e.event for e in mine] == ["token.revoked", "token.created"]
    ygg = await creds.list_events(tenant="ygg")
    assert {e.event for e in ygg} == {
        "token.created",
        "token.revoked",
        "credentials.gc",
    }
    assert all(e.user_id != other.id for e in ygg)
    assert len(await creds.list_events(tenant="ygg", limit=1)) == 1


async def test_clients_and_connected_apps(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    client = await make_client(db, name="Claude Code")
    other = await make_client(db, name="Desktop")
    family = uuid4()
    await insert_token(
        db, sara, TokenKind.OAUTH_REFRESH, family_id=family, client_id=client.client_id
    )
    await insert_token(
        db, sara, TokenKind.OAUTH_ACCESS, family_id=family, client_id=client.client_id
    )
    dead = uuid4()
    await insert_token(
        db,
        sara,
        TokenKind.OAUTH_REFRESH,
        family_id=dead,
        client_id=other.client_id,
        revoked_reason=REVOKED_ROTATED,
    )
    creds = CredentialRepository(db)

    apps = await creds.connected_apps(sara.id, _now())
    assert [(a.family_id, a.client_id, a.client_name) for a in apps] == [
        (family, client.client_id, "Claude Code")
    ]
    assert apps[0].redirect_uris == (LOOPBACK_REDIRECT,)
    assert await creds.live_family_counts(_now()) == {client.client_id: 1}
    listed = await creds.list_clients()
    assert {c.client_id for c in listed} == {client.client_id, other.client_id}
    assert await creds.client("missing") is None


async def test_rollback_discards_staged_writes(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    row, _ = await insert_token(db, user, TokenKind.PAT)
    token_id = row.id  # a rollback expires every loaded row
    creds = CredentialRepository(db)

    creds.add(CredentialEvent(event="token.revoked", user_id=user.id, via="api"))
    assert await creds.revoke_token(token_id, REVOKED_BY_USER, _now()) is True
    await creds.rollback()

    fresh = await creds.token(token_id, fresh=True)
    assert fresh is not None
    assert fresh.revoked_at is None
    assert await creds.list_events(tenant="ygg") == []


async def test_delete_stale_removes_only_dead_oauth_rows(db) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    now = _now()
    live_client = await make_client(db)
    idle_client = await make_client(db)
    revoked_client = await make_client(db, revoked=True)
    idle_with_tokens = await make_client(db)
    for stale in (idle_client, idle_with_tokens):
        stale.registered_at = now - timedelta(days=91)
        db.add(stale)
    await db.commit()

    pat, _ = await insert_token(
        db, sara, TokenKind.PAT, expires_in=timedelta(days=-400)
    )
    live_family = uuid4()
    live, _ = await insert_token(
        db,
        sara,
        TokenKind.OAUTH_REFRESH,
        family_id=live_family,
        client_id=live_client.client_id,
    )
    kept_on_idle, _ = await insert_token(
        db,
        sara,
        TokenKind.OAUTH_REFRESH,
        family_id=uuid4(),
        client_id=idle_with_tokens.client_id,
    )
    expired, _ = await insert_token(
        db,
        sara,
        TokenKind.OAUTH_ACCESS,
        family_id=live_family,
        client_id=live_client.client_id,
        expires_in=timedelta(days=-31),
    )
    long_revoked, _ = await insert_token(
        db,
        sara,
        TokenKind.OAUTH_REFRESH,
        family_id=uuid4(),
        client_id=revoked_client.client_id,
        revoked_reason=REVOKED_CLIENT,
    )
    long_revoked.revoked_at = now - timedelta(days=31)
    recently_revoked, _ = await insert_token(
        db,
        sara,
        TokenKind.OAUTH_ACCESS,
        family_id=live_family,
        client_id=live_client.client_id,
        revoked_reason=REVOKED_ROTATED,
    )
    db.add(long_revoked)
    await db.commit()
    old_code = await _code(db, sara, live_client, expires_in=timedelta(seconds=60))
    old_code.created_at = now - timedelta(days=2)
    db.add(old_code)
    new_code = await _code(db, sara, live_client, expires_in=timedelta(seconds=60))
    old_request = await _request(db, live_client, expires_in=timedelta(minutes=10))
    old_request.created_at = now - timedelta(days=2)
    db.add(old_request)
    new_request = await _request(db, live_client, expires_in=timedelta(minutes=10))
    await db.commit()
    creds = CredentialRepository(db)

    counts = await creds.delete_stale(now)
    await creds.commit()

    assert (counts.codes, counts.requests, counts.tokens, counts.clients) == (
        1,
        1,
        2,
        2,
    )
    for gone in (expired, long_revoked):
        assert await creds.token(gone.id, fresh=True) is None
    for kept in (pat, live, kept_on_idle, recently_revoked):
        assert await creds.token(kept.id, fresh=True) is not None
    assert await creds.code(old_code.id, fresh=True) is None
    assert await creds.code(new_code.id, fresh=True) is not None
    assert await creds.pending_request(new_request.id, now) is not None
    assert {c.client_id for c in await creds.list_clients()} == {
        live_client.client_id,
        idle_with_tokens.client_id,
    }


async def test_no_secret_helper_flags_leaks() -> None:
    secret = "atl_pat_" + "a" * 43
    assert_no_secret(secret, "nothing here", {"prefix": secret[:14]})
    with pytest.raises(AssertionError):
        assert_no_secret(secret, {"details": secret[14:30]})

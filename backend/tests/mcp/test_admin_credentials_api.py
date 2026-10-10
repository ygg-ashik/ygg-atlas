"""/admin credential routes: tokens, service accounts, clients, events (Task 8)."""

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, func, select

from app.access.models import RbacChange
from app.identity import (
    ApiToken,
    CredentialEvent,
    OAuthGrantError,
    TokenKind,
    User,
    hash_secret,
)
from tests.access_helpers import add_grant, make_user
from tests.identity.credential_helpers import assert_no_secret, insert_token
from tests.identity.oauth_helpers import (
    always_eligible,
    issued_pair,
    register_public_client,
)
from tests.mcp.api_helpers import api_app, as_user, client_for, oauth_service

ADMIN = "/api/v1/admin"


@pytest_asyncio.fixture
async def app() -> FastAPI:
    return api_app()


@pytest_asyncio.fixture
async def admin(db: AsyncSession) -> User:
    return await make_user(db, "root@yougotagift.com", role="admin")


@pytest_asyncio.fixture
async def ana(db: AsyncSession) -> User:
    return await make_user(db, "ana@yougotagift.com", role="analyst")


@pytest_asyncio.fixture
async def api(app: FastAPI, admin: User) -> AsyncIterator[AsyncClient]:
    as_user(app, admin)
    async with client_for(app) as client:
        yield client


async def _service_account(
    db: AsyncSession, name: str = "svc-bot", *, role: str = "analyst", **kw: str
) -> User:
    return await make_user(
        db, f"{name}@atlas.internal", role=role, kind="service", **kw
    )


async def _elsewhere(db: AsyncSession, user: User) -> User:
    user.tenant = "other-tenant"
    db.add(user)
    await db.commit()
    return user


async def _token(db: AsyncSession, token_id: UUID) -> ApiToken:
    row = await db.get(ApiToken, token_id, populate_existing=True)
    assert row is not None
    return row


async def _count(
    db: AsyncSession, model: type[RbacChange] | type[CredentialEvent]
) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_admin_lists_tokens_by_user_and_kind(
    api: AsyncClient, db: AsyncSession, ana: User
) -> None:
    pat, pat_raw = await insert_token(db, ana, TokenKind.PAT)
    oauth, _ = await insert_token(db, ana, TokenKind.OAUTH_ACCESS)
    refresh, _ = await insert_token(db, ana, TokenKind.OAUTH_REFRESH)
    bot = await _service_account(db)
    svc, _ = await insert_token(db, bot, TokenKind.SERVICE)

    every = await api.get(f"{ADMIN}/tokens")
    assert every.status_code == 200
    assert {t["id"] for t in every.json()} == {
        str(r.id) for r in (pat, oauth, refresh, svc)
    }
    assert all("token" not in t for t in every.json())
    assert_no_secret(pat_raw, every.text)

    anas = (await api.get(f"{ADMIN}/tokens", params={"user_id": str(ana.id)})).json()
    assert {t["id"] for t in anas} == {str(r.id) for r in (pat, oauth, refresh)}
    pats = (await api.get(f"{ADMIN}/tokens", params={"kind": "pat"})).json()
    assert [t["id"] for t in pats] == [str(pat.id)]
    oauths = (await api.get(f"{ADMIN}/tokens", params={"kind": "oauth"})).json()
    assert {t["id"] for t in oauths} == {str(oauth.id), str(refresh.id)}
    services = (await api.get(f"{ADMIN}/tokens", params={"kind": "service"})).json()
    assert [t["id"] for t in services] == [str(svc.id)]
    assert (
        await api.get(f"{ADMIN}/tokens", params={"kind": "oauth_refresh"})
    ).status_code == 422


async def test_admin_token_routes_need_admin_tokens(
    app: FastAPI, db: AsyncSession, ana: User
) -> None:
    row, _ = await insert_token(db, ana, TokenKind.PAT)
    bot = await _service_account(db)
    as_user(app, ana)
    async with client_for(app) as client:
        responses = [
            await client.get(f"{ADMIN}/tokens"),
            await client.delete(f"{ADMIN}/tokens/{row.id}"),
            await client.post(f"{ADMIN}/users/{ana.id}/tokens/revoke-all"),
            await client.post(
                f"{ADMIN}/service-accounts/{bot.id}/tokens", json={"name": "ci"}
            ),
        ]
    for resp in responses:
        assert resp.status_code == 403
        assert "admin:tokens" in resp.json()["detail"]
    assert (await _token(db, row.id)).revoked_at is None


async def test_admin_revokes_any_token_in_the_tenant(
    api: AsyncClient, db: AsyncSession, ana: User
) -> None:
    row, raw = await insert_token(db, ana, TokenKind.PAT)
    resp = await api.delete(f"{ADMIN}/tokens/{row.id}")
    assert resp.status_code == 204
    revoked = await _token(db, row.id)
    assert revoked.revoked_at is not None
    assert revoked.revoked_reason == "admin_revoked"
    assert_no_secret(raw, resp.text)


async def test_admin_revoking_an_oauth_access_token_cuts_the_whole_family(
    api: AsyncClient, db: AsyncSession, ana: User
) -> None:
    oauth = oauth_service(db)
    client_id = await register_public_client(oauth)
    pair = await issued_pair(oauth, ana, client_id)
    access = await _by_raw(db, pair.access_token)

    resp = await api.delete(f"{ADMIN}/tokens/{access.id}")

    assert resp.status_code == 204
    family = await _family(db, pair.family_id)
    assert {row.revoked_reason for row in family} == {"admin_revoked"}
    grant = await oauth.load_refresh(client_id, pair.refresh_token)
    assert grant is not None
    with pytest.raises(OAuthGrantError):  # the SDK answers invalid_grant
        await oauth.rotate_refresh(client_id, grant, always_eligible)


async def _by_raw(db: AsyncSession, raw: str) -> ApiToken:
    result = await db.execute(
        select(ApiToken).where(col(ApiToken.token_hash) == hash_secret(raw))
    )
    return result.scalar_one()


async def _family(db: AsyncSession, family_id: UUID) -> list[ApiToken]:
    result = await db.execute(
        select(ApiToken)
        .where(col(ApiToken.family_id) == family_id)
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


async def test_admin_cannot_see_or_revoke_another_tenants_tokens(
    api: AsyncClient, db: AsyncSession, ana: User
) -> None:
    await _elsewhere(db, ana)
    row, _ = await insert_token(db, ana, TokenKind.PAT)
    bot = await _elsewhere(db, await _service_account(db))

    assert (await api.get(f"{ADMIN}/tokens")).json() == []
    by_user = await api.get(f"{ADMIN}/tokens", params={"user_id": str(ana.id)})
    assert by_user.json() == []
    assert (await api.delete(f"{ADMIN}/tokens/{row.id}")).status_code == 404
    assert (
        await api.post(f"{ADMIN}/users/{ana.id}/tokens/revoke-all")
    ).status_code == 404
    assert (
        await api.post(f"{ADMIN}/service-accounts/{bot.id}/tokens", json={"name": "x"})
    ).status_code == 404
    assert (await _token(db, row.id)).revoked_at is None


async def test_revoke_all_for_a_user(
    api: AsyncClient, db: AsyncSession, ana: User
) -> None:
    first, _ = await insert_token(db, ana, TokenKind.PAT)
    second, _ = await insert_token(db, ana, TokenKind.OAUTH_ACCESS)
    resp = await api.post(f"{ADMIN}/users/{ana.id}/tokens/revoke-all")
    assert resp.status_code == 200
    assert resp.json() == {"revoked": 2}
    for row in (first, second):
        assert (await _token(db, row.id)).revoked_reason == "admin_revoked"
    unknown = "00000000-0000-0000-0000-000000000000"
    missing = await api.post(f"{ADMIN}/users/{unknown}/tokens/revoke-all")
    assert missing.status_code == 404


async def test_revoke_all_reaches_a_disabled_user_with_live_tokens(
    api: AsyncClient, db: AsyncSession
) -> None:
    """The cleanup tool when the disable hook (D18) failed to revoke."""
    off = await make_user(db, "gone@yougotagift.com", status="disabled")
    first, _ = await insert_token(db, off, TokenKind.PAT)
    second, _ = await insert_token(db, off, TokenKind.OAUTH_REFRESH)
    resp = await api.post(f"{ADMIN}/users/{off.id}/tokens/revoke-all")
    assert resp.status_code == 200
    assert resp.json() == {"revoked": 2}
    for row in (first, second):
        assert (await _token(db, row.id)).revoked_reason == "admin_revoked"


async def test_revoke_all_hides_a_disabled_user_in_another_tenant(
    api: AsyncClient, db: AsyncSession
) -> None:
    off = await _elsewhere(
        db, await make_user(db, "far@yougotagift.com", status="disabled")
    )
    row, _ = await insert_token(db, off, TokenKind.PAT)
    resp = await api.post(f"{ADMIN}/users/{off.id}/tokens/revoke-all")
    assert resp.status_code == 404
    assert (await _token(db, row.id)).revoked_at is None


async def test_create_service_account_needs_admin_users(
    app: FastAPI, api: AsyncClient, db: AsyncSession, admin: User, ana: User
) -> None:
    created = await api.post(
        f"{ADMIN}/service-accounts", json={"name": "Nightly Export", "role": "analyst"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["email"] == "svc-nightly-export@atlas.internal"
    assert body["display_name"] == "Nightly Export"
    assert body["kind"] == "service"
    assert body["role"] == "analyst"
    assert body["status"] == "active"
    assert body["owner_user_id"] == str(admin.id)

    duplicate = await api.post(
        f"{ADMIN}/service-accounts", json={"name": "nightly export", "role": "analyst"}
    )
    assert duplicate.status_code == 409
    too_long = await api.post(
        f"{ADMIN}/service-accounts", json={"name": "x" * 61, "role": "analyst"}
    )
    assert too_long.status_code == 422
    extra = await api.post(
        f"{ADMIN}/service-accounts",
        json={"name": "bot-two", "role": "analyst", "tenant": "other"},
    )
    assert extra.status_code == 422

    as_user(app, ana)
    async with client_for(app) as client:
        refused = await client.post(
            f"{ADMIN}/service-accounts", json={"name": "sneaky", "role": "analyst"}
        )
    assert refused.status_code == 403
    assert "admin:users" in refused.json()["detail"]


async def test_mint_service_token_needs_admin_tokens(
    app: FastAPI, api: AsyncClient, db: AsyncSession, ana: User
) -> None:
    bot = await _service_account(db)
    minted = await api.post(
        f"{ADMIN}/service-accounts/{bot.id}/tokens",
        json={"name": "ci", "expires_in_days": 30},
    )
    assert minted.status_code == 201
    body = minted.json()
    raw = body["token"]
    assert raw.startswith("atl_svc_")
    assert body["kind"] == "service"
    assert body["user_id"] == str(bot.id)

    listed = await api.get(f"{ADMIN}/tokens", params={"user_id": str(bot.id)})
    assert [t["id"] for t in listed.json()] == [body["id"]]
    assert_no_secret(raw, listed.text)
    events = (await db.execute(select(CredentialEvent))).scalars().all()
    assert_no_secret(raw, [e.model_dump() for e in events])

    as_user(app, ana)
    async with client_for(app) as client:
        refused = await client.post(
            f"{ADMIN}/service-accounts/{bot.id}/tokens", json={"name": "ci"}
        )
    assert refused.status_code == 403


async def test_mint_refused_for_a_human_or_disabled_account(
    api: AsyncClient, db: AsyncSession, ana: User
) -> None:
    human = await api.post(
        f"{ADMIN}/service-accounts/{ana.id}/tokens", json={"name": "ci"}
    )
    assert human.status_code == 400
    disabled = await _service_account(db, "svc-off", status="disabled")
    off = await api.post(
        f"{ADMIN}/service-accounts/{disabled.id}/tokens", json={"name": "ci"}
    )
    assert off.status_code == 404
    unknown = "00000000-0000-0000-0000-000000000000"
    missing = await api.post(
        f"{ADMIN}/service-accounts/{unknown}/tokens", json={"name": "ci"}
    )
    assert missing.status_code == 404
    assert (await _count(db, CredentialEvent)) == 0


async def test_mint_refused_when_the_account_outranks_the_actor(
    app: FastAPI, db: AsyncSession
) -> None:
    """D34: admin:tokens alone cannot mint a token for an admin service account."""
    token_admin = await make_user(db, "tok@yougotagift.com", role="builder")
    await add_grant(db, token_admin, "admin:tokens", kind="capability")
    strong = await _service_account(db, "svc-strong", role="admin")
    weak = await _service_account(db, "svc-weak", role="analyst")
    as_user(app, token_admin)
    async with client_for(app) as client:
        refused = await client.post(
            f"{ADMIN}/service-accounts/{strong.id}/tokens", json={"name": "ci"}
        )
        allowed = await client.post(
            f"{ADMIN}/service-accounts/{weak.id}/tokens", json={"name": "ci"}
        )
    assert refused.status_code == 403
    assert "more access than your own" in refused.json()["detail"]
    assert allowed.status_code == 201


async def test_list_and_revoke_clients_cascades_to_tokens(
    api: AsyncClient, db: AsyncSession, ana: User
) -> None:
    service = oauth_service(db)
    client_id = await register_public_client(service)
    pair = await issued_pair(service, ana, client_id)

    listed = await api.get(f"{ADMIN}/clients")
    assert listed.status_code == 200
    (client,) = listed.json()
    assert client["client_id"] == client_id
    assert client["client_name"] == "Claude Code"
    assert client["active_families"] == 1
    assert client["revoked_at"] is None
    assert_no_secret(pair.access_token, listed.text)

    assert (await api.delete(f"{ADMIN}/clients/{client_id}")).status_code == 204
    tokens = (
        (
            await db.execute(
                select(ApiToken)
                .where(col(ApiToken.client_id) == client_id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    assert tokens
    assert all(t.revoked_reason == "client_revoked" for t in tokens)
    (after,) = (await api.get(f"{ADMIN}/clients")).json()
    assert after["revoked_at"] is not None
    assert after["active_families"] == 0
    assert (await api.delete(f"{ADMIN}/clients/{client_id}")).status_code == 404
    assert (await api.delete(f"{ADMIN}/clients/no-such-client")).status_code == 404
    assert (await api.delete(f"{ADMIN}/clients/{'x' * 256}")).status_code == 422


async def test_client_routes_need_admin_clients(
    app: FastAPI, db: AsyncSession, ana: User
) -> None:
    client_id = await register_public_client(oauth_service(db))
    as_user(app, ana)
    async with client_for(app) as client:
        for resp in (
            await client.get(f"{ADMIN}/clients"),
            await client.delete(f"{ADMIN}/clients/{client_id}"),
        ):
            assert resp.status_code == 403
            assert "admin:clients" in resp.json()["detail"]


async def test_credential_events_need_admin_audit_and_are_tenant_scoped(
    app: FastAPI, api: AsyncClient, db: AsyncSession, ana: User
) -> None:
    olga = await _elsewhere(
        db, await make_user(db, "olga@yougotagift.com", role="analyst")
    )
    mine, _ = await insert_token(db, ana, TokenKind.PAT)
    theirs, _ = await insert_token(db, olga, TokenKind.PAT)
    await register_public_client(oauth_service(db))  # a global, user-less event
    assert (await api.delete(f"{ADMIN}/tokens/{mine.id}")).status_code == 204
    db.add(CredentialEvent(event="token.revoked", via="cli", user_id=olga.id))
    await db.commit()

    resp = await api.get(f"{ADMIN}/credential-events")
    assert resp.status_code == 200
    events = resp.json()
    assert {e["event"] for e in events} == {"token.revoked", "client.registered"}
    assert all(e["user_id"] in (str(ana.id), None) for e in events)
    assert str(theirs.id) not in resp.text

    anas = (
        await api.get(f"{ADMIN}/credential-events", params={"user_id": str(ana.id)})
    ).json()
    assert [e["event"] for e in anas] == ["token.revoked"]
    one = await api.get(f"{ADMIN}/credential-events", params={"limit": 1})
    assert len(one.json()) == 1
    for limit in (0, 501):
        bad = await api.get(f"{ADMIN}/credential-events", params={"limit": limit})
        assert bad.status_code == 422

    as_user(app, ana)
    async with client_for(app) as client:
        refused = await client.get(f"{ADMIN}/credential-events")
    assert refused.status_code == 403
    assert "admin:audit" in refused.json()["detail"]


async def test_revocations_land_in_credential_events_not_rbac_changes(
    api: AsyncClient, db: AsyncSession, ana: User
) -> None:
    row, _ = await insert_token(db, ana, TokenKind.PAT)
    await insert_token(db, ana, TokenKind.OAUTH_ACCESS)
    client_id = await register_public_client(oauth_service(db))
    changes_before = await _count(db, RbacChange)
    events_before = await _count(db, CredentialEvent)

    assert (await api.delete(f"{ADMIN}/tokens/{row.id}")).status_code == 204
    assert (
        await api.post(f"{ADMIN}/users/{ana.id}/tokens/revoke-all")
    ).status_code == 200
    assert (await api.delete(f"{ADMIN}/clients/{client_id}")).status_code == 204

    assert await _count(db, RbacChange) == changes_before
    assert await _count(db, CredentialEvent) == events_before + 3

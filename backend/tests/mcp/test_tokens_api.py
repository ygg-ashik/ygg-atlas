"""/me/tokens: personal tokens, shown once, owned and capped (Task 8)."""

from collections.abc import AsyncIterator

import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select
from structlog.testing import capture_logs

from app.identity import ApiToken, TokenKind, User
from tests.access_helpers import make_user
from tests.identity.credential_helpers import assert_no_secret, insert_token
from tests.mcp.api_helpers import api_app, as_user, client_for, real_door


@pytest_asyncio.fixture
async def app() -> FastAPI:
    return api_app()


@pytest_asyncio.fixture
async def analyst(db: AsyncSession) -> User:
    return await make_user(db, "ana@yougotagift.com", role="analyst")


@pytest_asyncio.fixture
async def api(app: FastAPI, analyst: User) -> AsyncIterator[AsyncClient]:
    as_user(app, analyst)
    async with client_for(app) as client:
        yield client


async def _rows(db: AsyncSession, user: User) -> list[ApiToken]:
    result = await db.execute(
        select(ApiToken)
        .where(col(ApiToken.user_id) == user.id)
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


async def test_create_pat_returns_the_token_once(
    api: AsyncClient, db: AsyncSession, analyst: User
) -> None:
    created = await api.post("/api/v1/me/tokens", json={"name": "laptop"})
    assert created.status_code == 201
    body = created.json()
    raw = body["token"]
    assert raw.startswith("atl_pat_")
    assert body["prefix"] == raw[:14]
    assert body["kind"] == "pat"
    assert body["user_id"] == str(analyst.id)

    listed = await api.get("/api/v1/me/tokens")
    assert listed.status_code == 200
    assert [t["id"] for t in listed.json()] == [body["id"]]
    assert "token" not in listed.json()[0]
    assert_no_secret(raw, listed.text)

    rows = await _rows(db, analyst)
    assert len(rows) == 1
    assert_no_secret(raw, rows[0].model_dump())


async def test_create_pat_needs_tokens_create(app: FastAPI, db: AsyncSession) -> None:
    viewer = await make_user(db, "vic@yougotagift.com", role="viewer")
    as_user(app, viewer)
    async with client_for(app) as client:
        resp = await client.post("/api/v1/me/tokens", json={"name": "laptop"})
    assert resp.status_code == 403
    assert "tokens:create" in resp.json()["detail"]
    assert await _rows(db, viewer) == []


async def test_eleventh_pat_is_409(api: AsyncClient) -> None:
    for n in range(10):
        resp = await api.post("/api/v1/me/tokens", json={"name": f"t{n}"})
        assert resp.status_code == 201
    eleventh = await api.post("/api/v1/me/tokens", json={"name": "one too many"})
    assert eleventh.status_code == 409
    assert "Revoke one first" in eleventh.json()["detail"]


async def test_days_out_of_range_are_rejected(api: AsyncClient) -> None:
    for days in (0, 366):
        resp = await api.post(
            "/api/v1/me/tokens", json={"name": "x", "expires_in_days": days}
        )
        assert resp.status_code == 422
    ok = await api.post("/api/v1/me/tokens", json={"name": "x", "expires_in_days": 7})
    assert ok.status_code == 201


async def test_blank_name_is_a_rule_error(api: AsyncClient) -> None:
    resp = await api.post("/api/v1/me/tokens", json={"name": "   "})
    assert resp.status_code == 400
    assert "Name the token" in resp.json()["detail"]


async def test_list_shows_only_my_pats(
    api: AsyncClient, db: AsyncSession, analyst: User
) -> None:
    other = await make_user(db, "olga@yougotagift.com", role="analyst")
    await insert_token(db, other, TokenKind.PAT)
    await insert_token(db, analyst, TokenKind.OAUTH_ACCESS)
    mine = (await api.post("/api/v1/me/tokens", json={"name": "mine"})).json()

    listed = (await api.get("/api/v1/me/tokens")).json()
    assert [t["id"] for t in listed] == [mine["id"]]


async def test_revoke_my_token(
    api: AsyncClient, db: AsyncSession, analyst: User
) -> None:
    mine = (await api.post("/api/v1/me/tokens", json={"name": "mine"})).json()
    resp = await api.delete(f"/api/v1/me/tokens/{mine['id']}")
    assert resp.status_code == 204
    (row,) = await _rows(db, analyst)
    assert row.revoked_reason == "user_revoked"
    assert (await api.get("/api/v1/me/tokens")).json() == []
    again = await api.delete(f"/api/v1/me/tokens/{mine['id']}")
    assert again.status_code == 204  # idempotent


async def test_revoke_someone_elses_token_is_404(
    api: AsyncClient, db: AsyncSession
) -> None:
    other = await make_user(db, "olga@yougotagift.com", role="analyst")
    row, raw = await insert_token(db, other, TokenKind.PAT)
    resp = await api.delete(f"/api/v1/me/tokens/{row.id}")
    assert resp.status_code == 404
    assert_no_secret(raw, resp.text)
    (fresh,) = await _rows(db, other)
    assert fresh.revoked_at is None


async def test_extra_fields_are_rejected(api: AsyncClient) -> None:
    resp = await api.post(
        "/api/v1/me/tokens", json={"name": "x", "user_id": "someone-else"}
    )
    assert resp.status_code == 422
    assert "someone-else" not in resp.text  # validation errors never echo input


async def test_token_never_logged(api: AsyncClient) -> None:
    with capture_logs() as logs:
        created = await api.post("/api/v1/me/tokens", json={"name": "laptop"})
        raw = created.json()["token"]
        await api.get("/api/v1/me/tokens")
        await api.delete(f"/api/v1/me/tokens/{created.json()['id']}")
    assert logs, "the create and revoke are logged"
    assert_no_secret(raw, logs)


async def test_token_routes_need_a_bearer(app: FastAPI) -> None:
    real_door(app)
    async with client_for(app) as client:
        assert (await client.get("/api/v1/me/tokens")).status_code == 401
        assert (
            await client.post("/api/v1/me/tokens", json={"name": "x"})
        ).status_code == 401

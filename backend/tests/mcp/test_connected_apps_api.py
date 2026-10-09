"""/me/connected-apps: the OAuth consents a user can see and disconnect (Task 8)."""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.identity import (
    InvalidTokenError,
    TokenPair,
    User,
    authenticate_bearer,
)
from tests.access_helpers import make_user
from tests.identity.credential_helpers import assert_no_secret
from tests.identity.oauth_helpers import (
    issued_pair,
    register_public_client,
)
from tests.mcp.api_helpers import (
    api_app,
    as_user,
    client_for,
    oauth_service,
    real_door,
)

APPS = "/api/v1/me/connected-apps"


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


async def _connect(db: AsyncSession, user: User) -> tuple[str, TokenPair]:
    service = oauth_service(db)
    client_id = await register_public_client(service)
    return client_id, await issued_pair(service, user, client_id)


async def test_lists_my_live_families_with_redirect_host(
    api: AsyncClient, db: AsyncSession, analyst: User
) -> None:
    client_id, pair = await _connect(db, analyst)
    resp = await api.get(APPS)
    assert resp.status_code == 200
    (connected,) = resp.json()
    assert connected["family_id"] == str(pair.family_id)
    assert connected["client_id"] == client_id
    assert connected["client_name"] == "Claude Code"
    assert connected["redirect_host"] == "localhost"
    assert connected["expires_at"]
    assert_no_secret(pair.access_token, resp.text)
    assert_no_secret(pair.refresh_token, resp.text)


async def test_disconnect_revokes_the_family(
    api: AsyncClient, db: AsyncSession, analyst: User
) -> None:
    _, pair = await _connect(db, analyst)
    resp = await api.delete(f"{APPS}/{pair.family_id}")
    assert resp.status_code == 204
    assert (await api.get(APPS)).json() == []
    async with get_session_factory()() as fresh:  # the door's own session (Task 3)
        with pytest.raises(InvalidTokenError):
            await authenticate_bearer(fresh, pair.access_token)


async def test_cannot_disconnect_someone_elses_family(
    api: AsyncClient, db: AsyncSession
) -> None:
    olga = await make_user(db, "olga@yougotagift.com", role="analyst")
    _, pair = await _connect(db, olga)
    assert (await api.get(APPS)).json() == []
    resp = await api.delete(f"{APPS}/{pair.family_id}")
    assert resp.status_code == 404
    async with get_session_factory()() as fresh:
        bearer = await authenticate_bearer(fresh, pair.access_token)
    assert bearer.principal.user_id == olga.id


async def test_connected_apps_need_a_bearer(app: FastAPI) -> None:
    real_door(app)
    async with client_for(app) as client:
        assert (await client.get(APPS)).status_code == 401

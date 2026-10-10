"""A scripted OAuth client for the MCP authorization-server tests (Task 5).

`oauth_store` is a private database file with every table and no demo seed (the
shared `db` fixture seeds thousands of rows per test). `oauth_test_app` mounts the
discovery router at the root and the OAuth routes under `/mcp-server`, as main.py
does, over that store. The HTTP consent route is Task 8's, so `approve_directly`
approves through `OAuthService` as that route would.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, col
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount
from starlette.types import Message

import app.access.models
import app.identity.models
import app.models.audit  # noqa: F401  # every table for create_all
from app.access.cache import shared_cache
from app.access.models import PolicyState
from app.config import Settings, get_settings
from app.identity import ApiToken, OAuthConfig, OAuthService, User
from app.mcp.auth import AtlasTokenVerifier
from app.mcp.oauth_provider import AtlasOAuthProvider
from app.mcp.oauth_routes import build_oauth_routes, discovery_router
from tests.identity.credential_helpers import LOOPBACK_REDIRECT
from tests.identity.oauth_helpers import pkce_pair, query_param

BASE = "http://localhost:8080"
ISSUER = f"{BASE}/mcp-server"
RESOURCE = f"{ISSUER}/mcp"
CONSENT = f"{BASE}/oauth/consent"
FORM = {"content-type": "application/x-www-form-urlencoded"}


SessionFactory = Callable[[], async_sessionmaker[AsyncSession]]


def pkce() -> tuple[str, str]:
    """(verifier, S256 challenge)."""
    return pkce_pair()


@dataclass(frozen=True)
class Store:
    """A test's own database: `db` for setup and asserts, `sessions` for the code
    under test (one fresh session per call, as in production)."""

    db: AsyncSession
    sessions: SessionFactory


@asynccontextmanager
async def oauth_store(directory: Path) -> AsyncIterator[Store]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{directory / 'oauth.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    shared_cache().clear()
    try:
        async with maker() as db:
            db.add(PolicyState())
            await db.commit()
            yield Store(db, lambda: maker)
    finally:
        await engine.dispose()


@dataclass(frozen=True)
class OAuthTestApp:
    app: FastAPI
    provider: AtlasOAuthProvider
    verifier: AtlasTokenVerifier
    config: OAuthConfig


def oauth_test_app(store: Store, settings: Settings | None = None) -> OAuthTestApp:
    resolved = settings or get_settings()
    config = OAuthConfig.from_settings(resolved)
    verifier = AtlasTokenVerifier(config.resource, store.sessions)
    provider = AtlasOAuthProvider(config, verifier, sessions=store.sessions)
    app = FastAPI()
    app.include_router(discovery_router)
    app.router.routes.append(
        Mount("/mcp-server", app=Starlette(routes=build_oauth_routes(provider, config)))
    )
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    return OAuthTestApp(app, provider, verifier, config)


@asynccontextmanager
async def http(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE
    ) as client:
        yield client


async def register(
    client: httpx.AsyncClient,
    *,
    redirect: str = LOOPBACK_REDIRECT,
    auth_method: str = "none",
) -> dict[str, str]:
    response = await client.post(
        "/mcp-server/register",
        json={
            "client_name": "Claude Code",
            "redirect_uris": [redirect],
            "token_endpoint_auth_method": auth_method,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def authorize_response(
    client: httpx.AsyncClient,
    client_id: str,
    challenge: str | None,
    *,
    redirect: str = LOOPBACK_REDIRECT,
    state: str = "state-1",
    resource: str | None = RESOURCE,
    method: str = "S256",
) -> httpx.Response:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "code_challenge": challenge,
        "code_challenge_method": method,
        "state": state,
        "resource": resource,
    }
    return await client.get(
        "/mcp-server/authorize",
        params={key: value for key, value in params.items() if value is not None},
    )


async def authorize(
    client: httpx.AsyncClient,
    client_id: str,
    challenge: str,
    *,
    redirect: str = LOOPBACK_REDIRECT,
    state: str = "state-1",
) -> str:
    """Runs /authorize and returns the raw txn from the consent redirect."""
    response = await authorize_response(
        client, client_id, challenge, redirect=redirect, state=state
    )
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(f"{CONSENT}?txn=")
    return query_param(location, "txn")


async def approve_directly(store: Store, txn: str, user: User) -> tuple[str, str]:
    """Approves as the consent API would: (raw code, state)."""
    async with store.sessions()() as db:
        redirect = await OAuthService(db, _config()).approve(txn, user.id)
    return query_param(redirect, "code"), query_param(redirect, "state")


def _config() -> OAuthConfig:
    return OAuthConfig.from_settings(get_settings())


def _secret_fields(secret: str | None) -> dict[str, str]:
    return {} if secret is None else {"client_secret": secret}


async def exchange(
    client: httpx.AsyncClient,
    client_id: str,
    code: str,
    verifier: str | None,
    *,
    redirect: str | None = LOOPBACK_REDIRECT,
    secret: str | None = None,
) -> httpx.Response:
    fields = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect,
    } | _secret_fields(secret)
    body = {key: value for key, value in fields.items() if value is not None}
    return await client.post("/mcp-server/token", data=body)


async def refresh(
    client: httpx.AsyncClient,
    client_id: str,
    refresh_token: str,
    *,
    secret: str | None = None,
) -> httpx.Response:
    body = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    } | _secret_fields(secret)
    return await client.post("/mcp-server/token", data=body)


async def revoke(
    client: httpx.AsyncClient,
    client_id: str,
    token: str,
    *,
    hint: str | None = None,
    secret: str | None = None,
) -> httpx.Response:
    body = {"client_id": client_id, "token": token} | _secret_fields(secret)
    if hint is not None:
        body["token_type_hint"] = hint
    return await client.post("/mcp-server/revoke", data=body)


async def tokens_for(
    store: Store, client: httpx.AsyncClient, user: User
) -> tuple[str, dict[str, str]]:
    """Register -> authorize -> approve -> token for a public client:
    (client_id, token response)."""
    client_id = (await register(client))["client_id"]
    verifier, challenge = pkce()
    code, _ = await approve_directly(
        store, await authorize(client, client_id, challenge), user
    )
    response = await exchange(client, client_id, code, verifier)
    assert response.status_code == 200, response.text
    return client_id, response.json()


async def age_rotation(db: AsyncSession, token_id: UUID, seconds: int) -> None:
    """Moves a rotated token's revoked_at back: the grace window uses the service
    clock, and SDK paths use wall time (C14), so tests age rows instead."""
    row = await db.get(ApiToken, token_id, populate_existing=True)
    assert row is not None
    assert row.revoked_at is not None
    await db.execute(
        update(ApiToken)
        .where(col(ApiToken.id) == token_id)
        .values(revoked_at=row.revoked_at - timedelta(seconds=seconds))
    )
    await db.commit()


def form_request(
    fields: dict[str, str], headers: dict[str, str] | None = None
) -> Request:
    """A form-encoded POST for testing the client authenticator directly."""
    body = urlencode(fields).encode()
    raw_headers = [(b"content-type", FORM["content-type"].encode())] + [
        (name.lower().encode(), value.encode())
        for name, value in (headers or {}).items()
    ]
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp-server/token",
        "headers": raw_headers,
        "query_string": b"",
    }
    return Request(scope, receive)

"""get_principal through a real FastAPI app, with Firebase faked."""

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.identity.dependencies import get_principal, get_token_verifier
from app.identity.errors import IdentityUnavailableError
from app.identity.principal import Principal
from app.identity.tokens import InvalidTokenError, VerifiedToken

ClientFactory = Callable[..., AsyncClient]


class FakeVerifier:
    def __init__(self, email: str) -> None:
        self.email = email

    async def verify(self, token: str) -> VerifiedToken:
        if token == "outage":
            raise IdentityUnavailableError("certs")
        if token not in {"good", "stale"}:
            raise InvalidTokenError("bad")
        signed_in = 0 if token == "stale" else int(datetime.now(UTC).timestamp())
        return VerifiedToken(
            uid="fb-sara",
            email=self.email,
            email_verified=True,
            name="Sara",
            auth_time=signed_in,
            sign_in_provider="google.com",
        )

    async def revoke(self, firebase_uid: str) -> None:
        return None


def _app(auth_disabled: bool, verifier: FakeVerifier) -> FastAPI:
    app = FastAPI()

    @app.get("/who")
    async def who(principal: Principal = Depends(get_principal)) -> dict[str, str]:
        return {"email": principal.email, "method": principal.auth_method}

    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(
        {"environment": "test", "auth_disabled": auth_disabled}
    )
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    return app


@pytest_asyncio.fixture
async def client_factory(db) -> AsyncIterator[ClientFactory]:
    clients: list[AsyncClient] = []

    def make(
        auth_disabled: bool = False, email: str = "sara@yougotagift.com"
    ) -> AsyncClient:
        transport = ASGITransport(app=_app(auth_disabled, FakeVerifier(email)))
        client = AsyncClient(transport=transport, base_url="http://test")
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


GOOD = {"Authorization": "Bearer good"}


async def test_valid_token_resolves_principal(client_factory: ClientFactory) -> None:
    resp = await client_factory().get("/who", headers=GOOD)
    assert resp.status_code == 200
    assert resp.json() == {"email": "sara@yougotagift.com", "method": "web"}


async def test_missing_token_is_401_with_challenge(
    client_factory: ClientFactory,
) -> None:
    resp = await client_factory().get("/who")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_invalid_token_is_401(client_factory: ClientFactory) -> None:
    resp = await client_factory().get("/who", headers={"Authorization": "Bearer bad"})
    assert resp.status_code == 401


async def test_wrong_domain_is_403(client_factory: ClientFactory) -> None:
    resp = await client_factory(email="x@gmail.com").get("/who", headers=GOOD)
    assert resp.status_code == 403


async def test_auth_disabled_returns_dev_principal(
    client_factory: ClientFactory,
) -> None:
    resp = await client_factory(auth_disabled=True).get("/who")
    assert resp.json() == {"email": "dev@yougotagift.com", "method": "dev"}


async def test_expired_session_is_401(client_factory: ClientFactory) -> None:
    resp = await client_factory().get("/who", headers={"Authorization": "Bearer stale"})
    assert resp.status_code == 401
    assert "Sign in again" in resp.json()["detail"]


async def test_verifier_outage_is_503_not_a_sign_out(
    client_factory: ClientFactory,
) -> None:
    resp = await client_factory().get(
        "/who", headers={"Authorization": "Bearer outage"}
    )
    assert resp.status_code == 503

"""GET /meta/auth-methods: what the account UI may offer (D22)."""

from fastapi import FastAPI

from app.config import Settings, get_settings
from tests.access_helpers import make_user
from tests.mcp.api_helpers import api_app, as_user, client_for, real_door

METHODS = "/api/v1/meta/auth-methods"


async def _methods(app: FastAPI) -> dict[str, object]:
    async with client_for(app) as client:
        resp = await client.get(METHODS)
    assert resp.status_code == 200
    return resp.json()


async def test_auth_methods_defaults(db) -> None:
    app = api_app()
    as_user(app, await make_user(db, "vic@yougotagift.com"))
    assert await _methods(app) == {
        "pat": {"enabled": True, "default_days": 90, "max_days": 365},
        "oauth": {"enabled": True, "hosted_connectors": False},
    }


async def test_hosted_connectors_with_an_https_public_url(db) -> None:
    app = api_app()
    as_user(app, await make_user(db, "vic@yougotagift.com"))
    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(
        {
            "environment": "test",
            "atlas_public_url": "https://atlas.example.com",
            "pat_default_days": 30,
            "pat_max_days": 180,
        }
    )
    assert await _methods(app) == {
        "pat": {"enabled": True, "default_days": 30, "max_days": 180},
        "oauth": {"enabled": True, "hosted_connectors": True},
    }


async def test_auth_methods_needs_authentication(db) -> None:
    app = api_app()
    real_door(app)
    async with client_for(app) as client:
        assert (await client.get(METHODS)).status_code == 401

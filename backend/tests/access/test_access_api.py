from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.access import AccessError, access_error_handler, require_capability
from app.access.catalog import ADMIN_AUDIT
from app.access.dependencies import get_policy
from app.access.errors import AccessDeniedError, PolicyUnavailableError
from app.access.models import PolicyState
from app.access.policy import Policy
from app.config import Settings, get_settings
from app.main import app as asgi_app
from tests.access_helpers import add_grant, add_member, make_group, make_user


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def api(db) -> AsyncIterator[AsyncClient]:
    async with _client(asgi_app) as client:
        yield client


async def test_a_new_user_can_chat_but_has_no_data(api: AsyncClient) -> None:
    body = (await api.get("/api/v1/me/access")).json()
    assert body == {
        "role": "viewer",
        "capabilities": ["chat:use"],
        "groups": [],
        "has_data_access": False,
    }


async def test_memberships_and_data_access_show_up(api: AsyncClient, db) -> None:
    dev = await make_user(db, "dev@yougotagift.com")
    group = await make_group(db, "growth")
    await add_member(db, group, dev, "manager")
    await add_grant(db, group, "demo/*")

    body = (await api.get("/api/v1/me/access")).json()

    assert body["groups"] == [
        {"id": str(group.id), "name": "growth", "standing": "manager"}
    ]
    assert body["has_data_access"] is True


async def test_capability_catalog_lists_roles(api: AsyncClient) -> None:
    body = (await api.get("/api/v1/meta/capabilities")).json()
    roles = {r["name"]: set(r["capabilities"]) for r in body["roles"]}
    assert roles["viewer"] == {"chat:use"}
    assert {c["code"] for c in body["capabilities"]} == roles["admin"]


async def test_an_unreadable_policy_is_a_503(api: AsyncClient, db) -> None:
    await db.execute(delete(PolicyState))
    await db.commit()
    assert (await api.get("/api/v1/me/access")).status_code == 503


async def test_require_capability_gates_a_route(db) -> None:
    app = FastAPI()

    @app.get("/audit", dependencies=[Depends(require_capability(ADMIN_AUDIT))])
    async def audit() -> dict[str, str]:
        return {"ok": "yes"}

    async with _client(app) as client:
        denied = await client.get("/audit")
        assert denied.status_code == 403
        assert "admin:audit" in denied.json()["detail"]

        await make_user(db, "dev@yougotagift.com", role="admin")
        assert (await client.get("/audit")).status_code == 200


def test_an_unknown_capability_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="Unknown capability"):
        require_capability("nope:nope")


async def test_a_disabled_dev_user_is_not_rejected_by_identity(
    api: AsyncClient, db
) -> None:
    """Finding: under AUTH_DISABLED, IdentityService.ensure_dev_user does not
    check user.status, so a disabled dev user still passes identity and gets a
    200 from /me/access. Only the evaluated Policy fails closed: no
    capabilities, no groups, no data access (see the next test for a route
    that does deny a disabled user)."""
    await make_user(db, "dev@yougotagift.com", status="disabled")

    response = await api.get("/api/v1/me/access")

    assert response.status_code == 200
    body = response.json()
    assert body["capabilities"] == []
    assert body["groups"] == []
    assert body["has_data_access"] is False


async def test_require_capability_denies_a_disabled_user(db) -> None:
    await make_user(db, "dev@yougotagift.com", role="admin", status="disabled")
    app = FastAPI()

    @app.get("/audit", dependencies=[Depends(require_capability(ADMIN_AUDIT))])
    async def audit() -> dict[str, str]:
        return {"ok": "yes"}

    async with _client(app) as client:
        assert (await client.get("/audit")).status_code == 403


async def test_require_capability_is_503_when_the_policy_is_unavailable(db) -> None:
    app = FastAPI()

    @app.get("/audit", dependencies=[Depends(require_capability(ADMIN_AUDIT))])
    async def audit() -> dict[str, str]:
        return {"ok": "yes"}

    await db.execute(delete(PolicyState))
    await db.commit()

    async with _client(app) as client:
        assert (await client.get("/audit")).status_code == 503


async def test_require_capability_denies_a_deny_all_policy() -> None:
    app = FastAPI()

    @app.get("/audit", dependencies=[Depends(require_capability(ADMIN_AUDIT))])
    async def audit() -> dict[str, str]:
        return {"ok": "yes"}

    app.dependency_overrides[get_policy] = lambda: Policy.deny_all(uuid4(), "ygg", 1)

    async with _client(app) as client:
        assert (await client.get("/audit")).status_code == 403


async def test_capabilities_requires_a_bearer_token_when_auth_is_enabled() -> None:
    enabled = Settings.model_validate({"environment": "test", "auth_disabled": False})
    asgi_app.dependency_overrides[get_settings] = lambda: enabled
    try:
        async with _client(asgi_app) as client:
            response = await client.get("/api/v1/meta/capabilities")
    finally:
        del asgi_app.dependency_overrides[get_settings]

    assert response.status_code == 401


async def test_access_error_handler_maps_status_and_message() -> None:
    app = FastAPI()
    app.add_exception_handler(AccessError, access_error_handler)

    @app.get("/denied")
    async def denied() -> None:
        raise AccessDeniedError("x")

    @app.get("/unavailable")
    async def unavailable() -> None:
        raise PolicyUnavailableError("y")

    async with _client(app) as client:
        denied_response = await client.get("/denied")
        unavailable_response = await client.get("/unavailable")

    assert denied_response.status_code == 403
    assert denied_response.json() == {"detail": "x"}
    assert unavailable_response.status_code == 503
    # The internal reason is logged, never sent: clients get a business message.
    assert unavailable_response.json() == {
        "detail": "The access check is unavailable right now."
    }

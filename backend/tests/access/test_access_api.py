from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.access import require_capability
from app.access.catalog import ADMIN_AUDIT
from app.access.models import PolicyState
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

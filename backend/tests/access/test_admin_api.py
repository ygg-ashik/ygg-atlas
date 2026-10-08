from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app as asgi_app
from tests.access_helpers import make_user

REVENUE = "demo/order/revenue"


@pytest_asyncio.fixture
async def api(db) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=asgi_app), base_url="http://test"
    ) as client:
        yield client


async def test_an_admin_grants_a_group_and_the_preview_explains_it(
    api: AsyncClient, db
) -> None:
    await make_user(db, "dev@yougotagift.com", role="admin")
    sara = await make_user(db, "sara@yougotagift.com")

    group = await api.post("/api/v1/admin/groups", json={"name": "growth"})
    assert group.status_code == 201
    group_id = group.json()["id"]
    member = await api.put(
        f"/api/v1/admin/groups/{group_id}/members/{sara.id}", json={}
    )
    assert member.json()["email"] == "sara@yougotagift.com"
    grant = await api.post(
        "/api/v1/admin/grants",
        json={"subject_type": "group", "subject_id": group_id, "target": "demo/*"},
    )
    assert grant.status_code == 201

    preview = (
        await api.get(
            f"/api/v1/admin/users/{sara.id}/access", params={"resource": REVENUE}
        )
    ).json()
    assert preview["decision"]["allowed"] is True
    assert "group:growth" in preview["decision"]["reason"]

    assert (
        await api.delete(f"/api/v1/admin/grants/{grant.json()['id']}")
    ).status_code == 204
    preview = (
        await api.get(
            f"/api/v1/admin/users/{sara.id}/access", params={"resource": REVENUE}
        )
    ).json()
    assert preview["decision"]["allowed"] is False

    changes = (await api.get("/api/v1/admin/rbac-changes")).json()
    assert [c["action"] for c in changes[:4]] == [
        "grant.revoke",
        "grant.create",
        "member.put",
        "group.create",
    ]


async def test_viewers_cannot_administer(api: AsyncClient) -> None:
    resp = await api.get("/api/v1/admin/groups")
    assert resp.status_code == 403
    assert "admin:groups" in resp.json()["detail"]


async def test_errors_map_to_status_codes(api: AsyncClient, db) -> None:
    dev = await make_user(db, "dev@yougotagift.com", role="admin")
    await api.post("/api/v1/admin/groups", json={"name": "growth"})

    duplicate = await api.post("/api/v1/admin/groups", json={"name": "growth"})
    assert duplicate.status_code == 409
    missing = await api.delete(
        "/api/v1/admin/groups/00000000-0000-0000-0000-000000000000"
    )
    assert missing.status_code == 404
    groups = (await api.get("/api/v1/admin/groups")).json()
    bad_pattern = await api.post(
        "/api/v1/admin/grants",
        json={
            "subject_type": "group",
            "subject_id": groups[0]["id"],
            "target": "demo order",
        },
    )
    assert bad_pattern.status_code == 422
    myself = await api.patch(f"/api/v1/admin/users/{dev.id}", json={"role": "viewer"})
    assert myself.status_code == 409


async def test_user_admin_lists_and_updates_users(api: AsyncClient, db) -> None:
    await make_user(db, "dev@yougotagift.com", role="admin")
    sara = await make_user(db, "sara@yougotagift.com")

    found = (await api.get("/api/v1/admin/users", params={"q": "sara"})).json()
    assert [u["email"] for u in found] == ["sara@yougotagift.com"]
    updated = await api.patch(
        f"/api/v1/admin/users/{sara.id}", json={"role": "analyst"}
    )
    assert updated.json()["role"] == "analyst"

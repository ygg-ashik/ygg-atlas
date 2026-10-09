from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.access.cache import PolicyCache
from app.access.dependencies import get_policy
from app.access.models import Group
from app.access.policy import Policy
from app.access.repository import AccessRepository
from app.access.service import AccessService
from app.identity.models import User
from app.main import app as asgi_app
from tests.access_helpers import add_member, make_group, make_user

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


# ---- reviewer follow-ups ----------------------------------------------------


async def test_a_malformed_resource_query_param_is_422(api: AsyncClient, db) -> None:
    await make_user(db, "dev@yougotagift.com", role="admin")
    sara = await make_user(db, "sara@yougotagift.com")

    resp = await api.get(
        f"/api/v1/admin/users/{sara.id}/access", params={"resource": "demo//x"}
    )

    assert resp.status_code == 422


async def test_an_overlong_search_query_is_422(api: AsyncClient, db) -> None:
    await make_user(db, "dev@yougotagift.com", role="admin")

    resp = await api.get("/api/v1/admin/users", params={"q": "x" * 101})

    assert resp.status_code == 422


async def test_rbac_changes_limit_is_bounded(api: AsyncClient, db) -> None:
    await make_user(db, "dev@yougotagift.com", role="admin")

    assert (
        await api.get("/api/v1/admin/rbac-changes", params={"limit": 0})
    ).status_code == 422
    assert (
        await api.get("/api/v1/admin/rbac-changes", params={"limit": 501})
    ).status_code == 422


async def test_a_manager_adds_members_but_cannot_appoint_one_or_see_other_groups(
    api: AsyncClient, db
) -> None:
    await make_user(db, "dev@yougotagift.com", role="admin")
    managed = await make_group(db, "growth")
    other = await make_group(db, "sales")
    manager_user = await make_user(db, "manager@yougotagift.com")
    await add_member(db, managed, manager_user, "manager")
    sara = await make_user(db, "sara@yougotagift.com")
    manager_id = manager_user.id

    async def manager_policy() -> Policy:
        # Resolved per request, as get_policy does: each write bumps the version.
        return await AccessService(AccessRepository(db), PolicyCache()).policy_for_user(
            manager_id
        )

    asgi_app.dependency_overrides[get_policy] = manager_policy
    try:
        added = await api.put(
            f"/api/v1/admin/groups/{managed.id}/members/{sara.id}", json={}
        )
        assert added.status_code == 200
        assert added.json()["standing"] == "member"

        appoint = await api.put(
            f"/api/v1/admin/groups/{managed.id}/members/{sara.id}",
            json={"standing": "manager"},
        )
        assert appoint.status_code == 403

        other_members = await api.get(f"/api/v1/admin/groups/{other.id}/members")
        assert other_members.status_code == 403
    finally:
        del asgi_app.dependency_overrides[get_policy]


async def test_cross_tenant_ids_are_not_found(api: AsyncClient, db) -> None:
    await make_user(db, "dev@yougotagift.com", role="admin")
    other_user = User(email="person@acme.example", tenant="acme")
    db.add(other_user)
    other_group = Group(name="acme-group", tenant="acme")
    db.add(other_group)
    await db.commit()

    user_resp = await api.get(f"/api/v1/admin/users/{other_user.id}/access")
    assert user_resp.status_code == 404

    group_resp = await api.patch(
        f"/api/v1/admin/groups/{other_group.id}", json={"name": "renamed"}
    )
    assert group_resp.status_code == 404


async def test_delete_group_204_has_an_empty_body(api: AsyncClient, db) -> None:
    await make_user(db, "dev@yougotagift.com", role="admin")
    group = await api.post("/api/v1/admin/groups", json={"name": "temp"})
    group_id = group.json()["id"]

    resp = await api.delete(f"/api/v1/admin/groups/{group_id}")

    assert resp.status_code == 204
    assert resp.content == b""


async def test_update_group_over_http(api: AsyncClient, db) -> None:
    await make_user(db, "dev@yougotagift.com", role="admin")
    group = await api.post("/api/v1/admin/groups", json={"name": "growth"})
    group_id = group.json()["id"]

    renamed = await api.patch(
        f"/api/v1/admin/groups/{group_id}", json={"name": "growth-mena"}
    )

    assert renamed.status_code == 200
    assert renamed.json()["name"] == "growth-mena"


async def test_list_members_and_remove_member_over_http(api: AsyncClient, db) -> None:
    await make_user(db, "dev@yougotagift.com", role="admin")
    sara = await make_user(db, "sara@yougotagift.com")
    group = await api.post("/api/v1/admin/groups", json={"name": "growth"})
    group_id = group.json()["id"]
    await api.put(f"/api/v1/admin/groups/{group_id}/members/{sara.id}", json={})

    listed = await api.get(f"/api/v1/admin/groups/{group_id}/members")
    assert [m["email"] for m in listed.json()] == ["sara@yougotagift.com"]

    removed = await api.delete(f"/api/v1/admin/groups/{group_id}/members/{sara.id}")
    assert removed.status_code == 204
    assert removed.content == b""

    listed_after = await api.get(f"/api/v1/admin/groups/{group_id}/members")
    assert listed_after.json() == []


async def test_list_grants_and_revoke_grant_over_http(api: AsyncClient, db) -> None:
    await make_user(db, "dev@yougotagift.com", role="admin")
    group = await api.post("/api/v1/admin/groups", json={"name": "growth"})
    group_id = group.json()["id"]
    created = await api.post(
        "/api/v1/admin/grants",
        json={"subject_type": "group", "subject_id": group_id, "target": "demo/*"},
    )
    grant_id = created.json()["id"]

    listed = await api.get(
        "/api/v1/admin/grants",
        params={"subject_type": "group", "subject_id": group_id},
    )
    assert [g["id"] for g in listed.json()] == [grant_id]

    revoked = await api.delete(f"/api/v1/admin/grants/{grant_id}")
    assert revoked.status_code == 204
    assert revoked.content == b""

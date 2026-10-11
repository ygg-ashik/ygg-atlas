"""Access requests over HTTP: shapes, gates and status codes."""

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.access.schemas import AccessRequestCreate
from app.identity.models import User
from app.main import app as asgi_app
from tests.access_helpers import (
    add_member,
    make_group,
    make_user,
    policy_of,
    requests_for,
)

REVENUE = "demo/order/revenue"
DEV = "dev@yougotagift.com"


@pytest_asyncio.fixture
async def api(db) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=asgi_app), base_url="http://test"
    ) as client:
        yield client


async def _ask(db, user: User, kind: str, target: str) -> str:
    payload = AccessRequestCreate.model_validate(
        {"kind": kind, "target": target, "note": "please"}
    )
    out = await requests_for(db).create(await policy_of(db, user), payload)
    return str(out.id)


async def test_me_requests_round_trip_shapes(api: AsyncClient, db) -> None:
    await make_user(db, DEV)

    created = await api.post(
        "/api/v1/me/requests",
        json={"kind": "resource", "target": REVENUE, "note": "Q4 review"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "pending"
    assert body["requester"] is None
    assert body["decided_by"] is None

    listed = (await api.get("/api/v1/me/requests")).json()
    assert [r["id"] for r in listed] == [body["id"]]

    duplicate = await api.post(
        "/api/v1/me/requests",
        json={"kind": "resource", "target": REVENUE, "note": "again"},
    )
    assert duplicate.status_code == 409

    cancelled = await api.post(f"/api/v1/me/requests/{body['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    again = await api.post(f"/api/v1/me/requests/{body['id']}/cancel")
    assert again.status_code == 409


async def test_create_validates_the_payload(api: AsyncClient, db) -> None:
    await make_user(db, DEV)

    for payload in (
        {"kind": "everything", "target": REVENUE, "note": "x"},
        {"kind": "resource", "target": REVENUE, "note": ""},
        {"kind": "resource", "target": "demo/*", "note": "x"},
        {"kind": "role", "target": "viewer", "note": "x"},
    ):
        resp = await api.post("/api/v1/me/requests", json=payload)
        assert resp.status_code == 422, payload


async def test_disabled_user_gets_403_on_me_requests(api: AsyncClient, db) -> None:
    await make_user(db, DEV, status="disabled")

    assert (await api.get("/api/v1/me/requests")).status_code == 403
    resp = await api.post(
        "/api/v1/me/requests",
        json={"kind": "resource", "target": REVENUE, "note": "x"},
    )
    assert resp.status_code == 403


async def test_options_shape_and_pattern_rejection(api: AsyncClient, db) -> None:
    await make_user(db, DEV)

    ok = await api.get("/api/v1/me/requests/options", params={"resource": REVENUE})
    assert ok.status_code == 200
    assert ok.json() == {
        "resource": REVENUE,
        "groups": [],
        "can_request_resource": True,
    }
    bad = await api.get("/api/v1/me/requests/options", params={"resource": "demo/*"})
    assert bad.status_code == 422
    missing = await api.get("/api/v1/me/requests/options")
    assert missing.status_code == 422


async def test_admin_requests_403_for_a_plain_viewer(api: AsyncClient, db) -> None:
    await make_user(db, DEV)

    resp = await api.get("/api/v1/admin/requests")

    assert resp.status_code == 403
    assert "group manager" in resp.json()["detail"]


async def test_admin_requests_page_embeds_the_requester(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")
    sara = await make_user(db, "sara@yougotagift.com")
    growth = await make_group(db, "growth")
    request_id = await _ask(db, sara, "group", str(growth.id))

    page = (await api.get("/api/v1/admin/requests")).json()

    assert page["next_cursor"] is None
    [item] = page["items"]
    assert item["id"] == request_id
    assert item["target_label"] == "growth"
    assert item["requester"] == {
        "user_id": str(sara.id),
        "email": "sara@yougotagift.com",
        "display_name": "",
        "role": "viewer",
    }
    assert (await api.get("/api/v1/admin/requests?status=approved")).json() == {
        "items": [],
        "next_cursor": None,
    }
    assert (
        len((await api.get("/api/v1/admin/requests?status=all")).json()["items"]) == 1
    )


async def test_admin_requests_query_bounds(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")

    for params in (
        {"limit": "0"},
        {"limit": "201"},
        {"status": "weird"},
        {"user_id": "not-a-uuid"},
        {"cursor": "tampered!"},
        {"cursor": "x" * 600},
    ):
        resp = await api.get("/api/v1/admin/requests", params=params)
        assert resp.status_code == 422, params


async def test_approve_and_decline_over_http(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")
    sara = await make_user(db, "sara@yougotagift.com")
    approve_me = await _ask(db, sara, "resource", REVENUE)
    decline_me = await _ask(db, sara, "role", "analyst")
    base = "/api/v1/admin/requests"

    unknown = await api.post(f"{base}/{uuid4()}/approve", json={})
    assert unknown.status_code == 404
    bad_expiry = await api.post(
        f"{base}/{decline_me}/approve", json={"expires_at": None}
    )
    assert bad_expiry.status_code == 422
    naive = await api.post(
        f"{base}/{approve_me}/approve", json={"expires_at": "2030-01-01T00:00:00"}
    )
    assert naive.status_code == 422

    approved = await api.post(f"{base}/{approve_me}/approve", json={"note": "ok"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_by"]["display_name"] == ""
    declined = await api.post(f"{base}/{decline_me}/decline", json={"note": "no"})
    assert declined.status_code == 200
    assert declined.json()["status"] == "declined"
    assert declined.json()["decision_note"] == "no"

    twice = await api.post(f"{base}/{approve_me}/decline", json={})
    assert twice.status_code == 409


async def test_decided_status_lists_approved_and_declined(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")
    sara = await make_user(db, "sara@yougotagift.com")
    approve_me = await _ask(db, sara, "resource", REVENUE)
    decline_me = await _ask(db, sara, "role", "analyst")
    cancel_me = await _ask(db, sara, "resource", "demo/order/count")
    pending = await _ask(db, sara, "role", "builder")
    base = "/api/v1/admin/requests"
    await api.post(f"{base}/{approve_me}/approve", json={})
    await api.post(f"{base}/{decline_me}/decline", json={})
    await requests_for(db).cancel(await policy_of(db, sara), UUID(cancel_me))

    decided = (await api.get(base, params={"status": "decided"})).json()["items"]
    assert sorted(r["id"] for r in decided) == sorted([approve_me, decline_me])
    assert {r["status"] for r in decided} == {"approved", "declined"}
    cancelled = (await api.get(base, params={"status": "cancelled"})).json()
    assert [r["id"] for r in cancelled["items"]] == [cancel_me]
    still = (await api.get(base)).json()["items"]
    assert [r["id"] for r in still] == [pending]


async def test_user_id_filter_stays_inside_the_scope(api: AsyncClient, db) -> None:
    growth = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    omar = await make_user(db, "omar@yougotagift.com")
    sara_group = await _ask(db, sara, "group", str(growth.id))
    await _ask(db, sara, "role", "analyst")  # outside a manager's scope
    await _ask(db, omar, "group", str(growth.id))
    dev = await make_user(db, DEV)
    await add_member(db, growth, dev, "manager")
    base = "/api/v1/admin/requests"

    mine = (await api.get(base, params={"user_id": str(sara.id)})).json()
    assert [r["id"] for r in mine["items"]] == [sara_group]
    nobody = (await api.get(base, params={"user_id": str(uuid4())})).json()
    assert nobody["items"] == []
    own = (await api.get(base, params={"user_id": str(dev.id)})).json()
    assert own["items"] == []

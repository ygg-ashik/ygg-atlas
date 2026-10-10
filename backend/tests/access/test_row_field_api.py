"""Row and field admin API (phase 3, T7): the shapes phase 5 binds to (K3)."""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.access.models import Group
from app.identity.models import User
from app.main import app as asgi_app
from tests.access_helpers import (
    add_grant,
    add_member,
    make_group,
    make_user,
    mirror_dimensions,
    seed_label_classes,
    set_attribute,
)

REVENUE = "demo/order/revenue"
ORDER_DIMENSIONS = [
    ("demo", "order", "channel", None),
    ("demo", "order", "sales_rep", "rep_name"),
]


@pytest_asyncio.fixture
async def api(db) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=asgi_app), base_url="http://test"
    ) as client:
        yield client


async def _dev(db, role: str = "admin") -> User:
    """The AUTH_DISABLED caller every request resolves to."""
    return await make_user(db, "dev@yougotagift.com", role=role)


async def _foreign_user(db) -> User:
    other = User(email="person@acme.example", tenant="acme")
    db.add(other)
    await db.commit()
    return other


# ---- grants carry a row scope ------------------------------------------------


async def test_a_scoped_grant_round_trips_over_http(api: AsyncClient, db) -> None:
    await _dev(db)
    await mirror_dimensions(db, ORDER_DIMENSIONS)
    group = await make_group(db, "b2c-team")

    created = await api.post(
        "/api/v1/admin/grants",
        json={
            "subject_type": "group",
            "subject_id": str(group.id),
            "target": "demo/order/*",
            "row_scope": {"channel": ["b2c", "b2c", "app"]},
        },
    )

    assert created.status_code == 201
    assert created.json()["row_scope"] == {"channel": ["app", "b2c"]}
    listed = await api.get(
        "/api/v1/admin/grants",
        params={"subject_type": "group", "subject_id": str(group.id)},
    )
    assert listed.json()[0]["row_scope"] == {"channel": ["app", "b2c"]}


async def test_bad_scopes_are_422(api: AsyncClient, db) -> None:
    await _dev(db)
    await mirror_dimensions(db, ORDER_DIMENSIONS)
    group = await make_group(db, "b2c-team")

    def body(scope: object, **extra: str) -> dict[str, object]:
        return {
            "subject_type": "group",
            "subject_id": str(group.id),
            "target": "demo/order/*",
            "row_scope": scope,
            **extra,
        }

    for bad in (
        body({}),
        body({"Channel": ["b2c"]}),
        body({"channel": []}),
        body({"region": ["AE"]}),  # not declared by demo/order
        body({"channel": ["b2c"]}, effect="deny"),
    ):
        resp = await api.post("/api/v1/admin/grants", json=bad)
        assert resp.status_code == 422, bad


async def test_a_clearance_grant_over_http(api: AsyncClient, db) -> None:
    dev = await _dev(db)
    await add_grant(db, dev, "fields:people_names", kind="clearance")
    group = await make_group(db, "csm")

    resp = await api.post(
        "/api/v1/admin/grants",
        json={
            "subject_type": "group",
            "subject_id": str(group.id),
            "target_kind": "clearance",
            "target": "fields:people_names",
        },
    )

    assert resp.status_code == 201
    assert resp.json()["target_kind"] == "clearance"
    assert resp.json()["row_scope"] is None


# ---- user attributes ---------------------------------------------------------


async def test_attributes_put_list_and_delete(api: AsyncClient, db) -> None:
    dev = await _dev(db)
    sara = await make_user(db, "sara@yougotagift.com")
    url = f"/api/v1/admin/users/{sara.id}/attributes"

    put = await api.put(f"{url}/rep_name", json={"value": "Sara K"})
    assert put.status_code == 200
    body = put.json()
    assert set(body) == {"key", "value", "set_by", "set_at"}
    assert (body["key"], body["value"], body["set_by"]) == (
        "rep_name",
        "Sara K",
        str(dev.id),
    )

    listed = await api.get(url)
    assert [(a["key"], a["value"]) for a in listed.json()] == [("rep_name", "Sara K")]

    deleted = await api.delete(f"{url}/rep_name")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert (await api.get(url)).json() == []
    assert (await api.delete(f"{url}/rep_name")).status_code == 404


async def test_attribute_input_errors(api: AsyncClient, db) -> None:
    dev = await _dev(db)
    sara = await make_user(db, "sara@yougotagift.com")
    url = f"/api/v1/admin/users/{sara.id}/attributes"

    assert (await api.put(f"{url}/Bad-Key", json={"value": "x"})).status_code == 422
    assert (await api.put(f"{url}/email", json={"value": "x"})).status_code == 422
    assert (await api.put(f"{url}/rep_name", json={"value": ""})).status_code == 422
    assert (
        await api.put(f"{url}/rep_name", json={"value": "x" * 201})
    ).status_code == 422
    myself = await api.put(
        f"/api/v1/admin/users/{dev.id}/attributes/rep_name", json={"value": "x"}
    )
    assert myself.status_code == 409


async def test_attribute_routes_need_admin_users(api: AsyncClient, db) -> None:
    await _dev(db, role="analyst")
    sara = await make_user(db, "sara@yougotagift.com")
    url = f"/api/v1/admin/users/{sara.id}/attributes"

    assert (await api.get(url)).status_code == 403
    assert (await api.put(f"{url}/rep_name", json={"value": "x"})).status_code == 403
    assert (await api.delete(f"{url}/rep_name")).status_code == 403


async def test_attribute_routes_hide_other_tenants(api: AsyncClient, db) -> None:
    await _dev(db)
    other = await _foreign_user(db)
    url = f"/api/v1/admin/users/{other.id}/attributes"

    assert (await api.get(url)).status_code == 404
    assert (await api.put(f"{url}/rep_name", json={"value": "x"})).status_code == 404
    assert (await api.delete(f"{url}/rep_name")).status_code == 404


async def test_there_is_no_bulk_attribute_put(api: AsyncClient, db) -> None:
    await _dev(db)
    sara = await make_user(db, "sara@yougotagift.com")

    resp = await api.put(
        f"/api/v1/admin/users/{sara.id}/attributes", json={"rep_name": "x"}
    )

    assert resp.status_code == 405


# ---- label classes -----------------------------------------------------------


async def test_label_classes_list_and_put(api: AsyncClient, db) -> None:
    await _dev(db)
    await seed_label_classes(db)

    listed = (await api.get("/api/v1/admin/label-classes")).json()
    assert [(c["label_class"], c["mode"]) for c in listed] == [
        ("business_name", "pseudonymise"),
        ("person_name", "suppress"),
    ]
    assert set(listed[0]) == {"label_class", "mode", "bucket_size", "updated_at"}

    put = await api.put(
        "/api/v1/admin/label-classes/person_name",
        json={"mode": "bucket", "bucket_size": 3},
    )
    assert put.status_code == 200
    assert (put.json()["mode"], put.json()["bucket_size"]) == ("bucket", 3)


async def test_label_class_errors(api: AsyncClient, db) -> None:
    await _dev(db)
    url = "/api/v1/admin/label-classes"

    assert (
        await api.put(f"{url}/category", json={"mode": "suppress"})
    ).status_code == 422
    assert (
        await api.put(f"{url}/person_name", json={"mode": "shout"})
    ).status_code == 422
    assert (
        await api.put(f"{url}/person_name", json={"mode": "bucket", "bucket_size": 51})
    ).status_code == 422


async def test_label_classes_need_admin_groups(api: AsyncClient, db) -> None:
    dev = await _dev(db, role="analyst")
    await add_grant(db, dev, "admin:users", kind="capability")

    assert (await api.get("/api/v1/admin/label-classes")).status_code == 403
    assert (
        await api.put(
            "/api/v1/admin/label-classes/person_name", json={"mode": "suppress"}
        )
    ).status_code == 403


# ---- scope dimensions --------------------------------------------------------


async def test_scope_dimensions_list_the_mirror(api: AsyncClient, db) -> None:
    await _dev(db)
    await mirror_dimensions(db, ORDER_DIMENSIONS)

    body = (await api.get("/api/v1/meta/scope-dimensions")).json()

    assert body == [
        {
            "source": "demo",
            "entity": "order",
            "dimension": "channel",
            "self_attribute": None,
            "description": "",
        },
        {
            "source": "demo",
            "entity": "order",
            "dimension": "sales_rep",
            "self_attribute": "rep_name",
            "description": "",
        },
    ]


async def test_scope_dimensions_need_a_grant_admin_capability(
    api: AsyncClient, db
) -> None:
    dev = await _dev(db, role="analyst")
    assert (await api.get("/api/v1/meta/scope-dimensions")).status_code == 403

    await add_grant(db, dev, "admin:users", kind="capability")
    assert (await api.get("/api/v1/meta/scope-dimensions")).status_code == 200


async def test_scope_dimensions_accept_admin_groups_alone(api: AsyncClient, db) -> None:
    dev = await _dev(db, role="analyst")
    await add_grant(db, dev, "admin:groups", kind="capability")

    assert (await api.get("/api/v1/meta/scope-dimensions")).status_code == 200


# ---- catalog, /me/access and the effective-access preview ---------------------


async def test_the_catalog_lists_clearances_label_classes_and_mask_modes(
    api: AsyncClient,
) -> None:
    body = (await api.get("/api/v1/meta/capabilities")).json()

    assert set(body) == {
        "capabilities",
        "roles",
        "clearances",
        "label_classes",
        "mask_modes",
    }
    assert {c["code"] for c in body["clearances"]} == {
        "fields:business_names",
        "fields:people_names",
    }
    assert all(c["description"] for c in body["clearances"])
    assert body["label_classes"] == ["category", "business_name", "person_name"]
    assert body["mask_modes"] == ["pseudonymise", "suppress", "bucket"]


async def test_me_access_shows_clearances(api: AsyncClient, db) -> None:
    dev = await _dev(db, role="viewer")
    await add_grant(db, dev, "fields:business_names", kind="clearance")

    body = (await api.get("/api/v1/me/access")).json()

    assert set(body) == {
        "role",
        "capabilities",
        "groups",
        "has_data_access",
        "clearances",
    }
    assert body["clearances"] == ["fields:business_names"]


async def _scoped_sara(db) -> tuple[User, Group]:
    await mirror_dimensions(db, ORDER_DIMENSIONS)
    sara = await make_user(db, "sara@yougotagift.com")
    group = await make_group(db, "b2c-team")
    await add_member(db, group, sara)
    await add_grant(db, group, REVENUE, row_scope={"channel": ["b2c"]})
    await add_grant(db, sara, "demo/order/*", row_scope={"sales_rep": ["$self"]})
    await add_grant(db, sara, "fields:people_names", kind="clearance")
    return sara, group


async def test_the_preview_shows_scopes_skips_and_clearances(
    api: AsyncClient, db
) -> None:
    await _dev(db)
    sara, _ = await _scoped_sara(db)

    body = (
        await api.get(
            f"/api/v1/admin/users/{sara.id}/access", params={"resource": REVENUE}
        )
    ).json()

    assert set(body) == {
        "user_id",
        "role",
        "active",
        "capabilities",
        "allow",
        "deny",
        "decision",
        "clearances",
        "skipped",
    }
    assert body["clearances"] == ["fields:people_names"]
    assert [(r["pattern"], r["row_scope"]) for r in body["allow"]] == [
        (REVENUE, {"channel": ["b2c"]})
    ]
    assert set(body["allow"][0]) == {"pattern", "grant_id", "origin", "row_scope"}
    assert [(s["pattern"], s["origin"]) for s in body["skipped"]] == [
        ("demo/order/*", "user")
    ]
    assert set(body["skipped"][0]) == {"pattern", "grant_id", "origin", "reason"}
    assert "rep_name" in body["skipped"][0]["reason"]
    assert set(body["decision"]) == {"resource", "allowed", "reason", "row_scope"}
    assert body["decision"]["allowed"] is True
    assert body["decision"]["row_scope"] == [{"channel": ["b2c"]}]


async def test_a_resolved_self_scope_shows_the_concrete_value(
    api: AsyncClient, db
) -> None:
    await _dev(db)
    sara, _ = await _scoped_sara(db)
    await set_attribute(db, sara, "rep_name", "Sara K")

    body = (
        await api.get(
            f"/api/v1/admin/users/{sara.id}/access", params={"resource": REVENUE}
        )
    ).json()

    assert body["skipped"] == []
    assert sorted(
        body["decision"]["row_scope"], key=lambda alt: sorted(alt.items())
    ) == [{"channel": ["b2c"]}, {"sales_rep": ["Sara K"]}]


async def test_the_preview_row_scope_is_null_when_unrestricted(
    api: AsyncClient, db
) -> None:
    await _dev(db)
    sara = await make_user(db, "sara@yougotagift.com")
    await add_grant(db, sara, "demo/*")

    body = (
        await api.get(
            f"/api/v1/admin/users/{sara.id}/access", params={"resource": REVENUE}
        )
    ).json()

    assert body["decision"]["allowed"] is True
    assert body["decision"]["row_scope"] is None
    assert body["allow"][0]["row_scope"] is None
    assert body["clearances"] == []
    assert body["skipped"] == []

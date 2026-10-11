"""GET /api/v1/atlas/catalog/resources: catalog metadata for the grant picker,
with an optional per-user access preview (phase 5, P5-D17/D18)."""

from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.catalog import ADMIN_GROUPS, ADMIN_USERS, CHAT_USE
from app.access.dependencies import get_policy
from app.access.policy import NO_GRANT, Policy
from app.atlas.policy import entity_resource, funnel_resource, metric_resource
from app.atlas.registry import get_registry
from app.identity.models import User
from app.main import app as asgi_app
from tests.access_helpers import add_grant, add_member, make_group, make_user

URL = "/api/v1/atlas/catalog/resources"
DEV = "dev@yougotagift.com"


@pytest_asyncio.fixture
async def api(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=asgi_app), base_url="http://test"
    ) as client:
        yield client
    asgi_app.dependency_overrides.pop(get_policy, None)


def _caller_with(*capabilities: str) -> Callable[[], Policy]:
    """A caller whose evaluated policy holds exactly these capabilities
    (no built-in role grants admin:groups without admin:users)."""
    policy = Policy(
        user_id=uuid4(),
        tenant="ygg",
        role="viewer",
        active=True,
        policy_version=1,
        capabilities=frozenset(capabilities),
    )
    return lambda: policy


def _items(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["path"]: item
        for source in body["sources"]
        for entity in source["entities"]
        for item in entity["items"]
    }


def _entities(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        entity["path"]: entity
        for source in body["sources"]
        for entity in source["entities"]
    }


async def test_admin_with_no_data_sees_full_metadata(
    api: AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, DEV, role="admin")  # D2: admin, but no grant to any data
    resp = await api.get(URL)
    assert resp.status_code == 200
    body = resp.json()
    registry = get_registry()
    assert [s["id"] for s in body["sources"]] == list(registry.plugins)
    assert set(_entities(body)) == {
        entity_resource(e) for e in registry.entities.values()
    }
    assert set(_items(body)) == {
        metric_resource(m) for m in registry.metrics.values()
    } | {funnel_resource(f) for f in registry.funnels.values()}
    assert body["as_user"] is None
    assert all(i["decision"] is None for i in _items(body).values())
    assert all(e["decision"] is None for e in _entities(body).values())
    demo = next(s for s in body["sources"] if s["id"] == "demo")
    assert demo["name"]
    revenue = _items(body)["demo/order/revenue"]
    assert (revenue["id"], revenue["kind"]) == ("revenue", "metric")
    assert _items(body)["demo/checkout/checkout_funnel"]["kind"] == "funnel"


async def test_admin_groups_alone_may_list(api: AsyncClient) -> None:
    asgi_app.dependency_overrides[get_policy] = _caller_with(ADMIN_GROUPS)
    resp = await api.get(URL)
    assert resp.status_code == 200
    assert resp.json()["sources"]


async def test_viewer_gets_403(api: AsyncClient, db: AsyncSession) -> None:
    await make_user(db, DEV, role="viewer")
    resp = await api.get(URL)
    assert resp.status_code == 403
    assert "admin:users or admin:groups" in resp.json()["detail"]


async def test_builder_gets_403(api: AsyncClient, db: AsyncSession) -> None:
    await make_user(db, DEV, role="builder")
    assert (await api.get(URL)).status_code == 403


async def test_as_user_needs_admin_users(api: AsyncClient, db: AsyncSession) -> None:
    sara = await make_user(db, "sara@yougotagift.com")
    asgi_app.dependency_overrides[get_policy] = _caller_with(ADMIN_GROUPS)
    resp = await api.get(URL, params={"as_user": str(sara.id)})
    assert resp.status_code == 403
    assert "admin:users" in resp.json()["detail"]


async def test_as_user_returns_the_targets_decisions_with_origin(
    api: AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, DEV, role="admin")
    sara = await make_user(db, "sara@yougotagift.com")
    growth = await make_group(db, "growth")
    await add_member(db, growth, sara)
    await add_grant(db, growth, "demo/order/*")
    await add_grant(db, sara, "demo/order/revenue", effect="deny")

    resp = await api.get(URL, params={"as_user": str(sara.id)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["as_user"] == str(sara.id)
    items = _items(body)

    allowed = items["demo/order/orders_count"]["decision"]
    assert allowed["allowed"] is True
    assert allowed["origin"] == "group:growth"

    denied = items["demo/order/revenue"]["decision"]
    assert denied["allowed"] is False
    assert denied["origin"] == "user"
    assert "denied by grant" in denied["reason"]

    nothing = items["demo/checkout/checkout_funnel"]["decision"]
    assert nothing == {"allowed": False, "reason": NO_GRANT, "origin": None}

    assert all(e["decision"] is not None for e in _entities(body).values())


async def test_as_user_from_another_tenant_is_404(
    api: AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, DEV, role="admin")
    other = User(email="person@acme.example", tenant="acme")
    db.add(other)
    await db.commit()
    assert (await api.get(URL, params={"as_user": str(other.id)})).status_code == 404
    assert (await api.get(URL, params={"as_user": str(uuid4())})).status_code == 404


async def test_paths_match_the_atlas_resource_builders(
    api: AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, DEV, role="admin")
    body = (await api.get(URL)).json()
    registry = get_registry()
    for source in body["sources"]:
        for entity in source["entities"]:
            entity_id = entity["path"].split("/")[-1]
            assert entity["path"] == entity_resource(registry.entities[entity_id])
            for item in entity["items"]:
                definition = (
                    registry.metrics[item["id"]]
                    if item["kind"] == "metric"
                    else registry.funnels[item["id"]]
                )
                builder = (
                    metric_resource if item["kind"] == "metric" else funnel_resource
                )
                assert item["path"] == builder(definition)  # type: ignore[arg-type]


def _numbers(value: object) -> list[object]:
    if isinstance(value, bool):
        return []
    if isinstance(value, int | float):
        return [value]
    if isinstance(value, dict):
        return [n for v in value.values() for n in _numbers(v)]  # type: ignore[union-attr]
    if isinstance(value, list):
        return [n for v in value for n in _numbers(v)]  # type: ignore[union-attr]
    return []


async def test_response_contains_no_numeric_values(
    api: AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, DEV, role="admin")
    sara = await make_user(db, "sara@yougotagift.com")
    await add_grant(db, sara, "demo/*")
    plain = (await api.get(URL)).json()
    preview = (await api.get(URL, params={"as_user": str(sara.id)})).json()
    assert _numbers(plain) == []
    assert _numbers(preview) == []


async def test_dashboard_routes_still_require_chat_use(api: AsyncClient) -> None:
    asgi_app.dependency_overrides[get_policy] = _caller_with(ADMIN_USERS)
    assert (await api.get("/api/v1/atlas/metrics")).status_code == 403
    assert (await api.get(URL)).status_code == 200
    asgi_app.dependency_overrides[get_policy] = _caller_with(CHAT_USE)
    assert (await api.get("/api/v1/atlas/metrics")).status_code == 200
    assert (await api.get(URL)).status_code == 403


async def test_no_scope_dimensions_are_embedded(
    api: AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, DEV, role="admin")
    body = (await api.get(URL)).json()

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {k for v in value.values() for k in keys(v)}  # type: ignore[union-attr]
        if isinstance(value, list):
            return {k for v in value for k in keys(v)}  # type: ignore[union-attr]
        return set()

    assert not {k for k in keys(body) if "dimension" in k}

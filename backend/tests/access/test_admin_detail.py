"""User and group detail, the user list's filters and cursor (phase 5, B5)."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.access.errors import AccessDeniedError, InvalidChangeError, NotFoundError
from app.access.models import Group
from app.access.schemas import AccessRequestCreate, UserQuery
from app.identity.models import User
from app.main import app as asgi_app
from tests.access_helpers import (
    actor_with,
    add_grant,
    add_member,
    admin_for,
    make_group,
    make_user,
    policy_of,
    requests_for,
)

DEV = "dev@yougotagift.com"


@pytest_asyncio.fixture
async def api(db) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=asgi_app), base_url="http://test"
    ) as client:
        yield client


async def _ask(db, user: User, kind: str, target: str) -> None:
    payload = AccessRequestCreate.model_validate(
        {"kind": kind, "target": target, "note": "please"}
    )
    await requests_for(db).create(await policy_of(db, user), payload)


async def _other_tenant(db) -> tuple[User, Group]:
    user = User(email="someone@acme.example", tenant="acme")
    group = Group(name="acme-group", tenant="acme")
    db.add_all([user, group])
    await db.commit()
    return user, group


# ---- user detail ------------------------------------------------------------


async def test_user_detail_lists_groups_direct_grants_and_pending_count(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    growth = await make_group(db, "growth")
    analytics = await make_group(db, "analytics")
    await add_member(db, growth, sara, "manager")
    await add_member(db, analytics, sara)
    grant = await add_grant(db, sara, "demo/*")
    await add_grant(db, growth, "demo/order/*")  # a group grant: not direct
    await _ask(db, sara, "role", "analyst")
    await _ask(db, sara, "resource", "deepsales/ds_task/ds_open_tasks")

    detail = await admin_for(db).users.user_detail(actor, sara.id)

    assert detail.email == "sara@yougotagift.com"
    assert detail.created_at is not None
    assert [(g.name, g.standing) for g in detail.groups] == [
        ("analytics", "member"),
        ("growth", "manager"),
    ]
    assert [g.id for g in detail.direct_grants] == [grant.id]
    assert detail.pending_requests == 2


async def test_user_detail_cross_tenant_is_404(db) -> None:
    actor = await actor_with(db)
    other, _ = await _other_tenant(db)

    for target in (other.id, uuid4()):
        with pytest.raises(NotFoundError):
            await admin_for(db).users.user_detail(actor, target)


async def test_user_detail_needs_admin_users(api: AsyncClient, db) -> None:
    await make_user(db, DEV)
    sara = await make_user(db, "sara@yougotagift.com")

    resp = await api.get(f"/api/v1/admin/users/{sara.id}")

    assert resp.status_code == 403
    assert "admin:users" in resp.json()["detail"]


async def test_user_detail_over_http(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")
    sara = await make_user(db, "sara@yougotagift.com")
    other, _ = await _other_tenant(db)

    body = (await api.get(f"/api/v1/admin/users/{sara.id}")).json()
    assert set(body) == {
        "id",
        "email",
        "display_name",
        "kind",
        "role",
        "status",
        "last_seen_at",
        "created_at",
        "groups",
        "direct_grants",
        "pending_requests",
    }
    assert (await api.get(f"/api/v1/admin/users/{other.id}")).status_code == 404


# ---- group detail -------------------------------------------------------------


async def test_group_detail_counts_and_path(db) -> None:
    actor = await actor_with(db)
    company = await make_group(db, "company")
    sales = await make_group(db, "sales", parent=company)
    emea = await make_group(db, "emea", parent=sales)
    for email in ("a@yougotagift.com", "b@yougotagift.com"):
        await add_member(db, emea, await make_user(db, email))
    await add_grant(db, emea, "demo/*")
    await add_grant(db, emea, "demo/order/*", effect="deny")

    detail = await admin_for(db).groups.group_detail(actor, emea.id)

    assert detail.name == "emea"
    assert detail.parent_id == sales.id
    assert detail.path == ["company", "sales", "emea"]
    assert (detail.member_count, detail.grant_count) == (2, 2)
    root = await admin_for(db).groups.group_detail(actor, company.id)
    assert root.path == ["company"]
    assert (root.member_count, root.grant_count) == (0, 0)


async def test_group_detail_for_a_manager_of_an_ancestor(db) -> None:
    sales = await make_group(db, "sales")
    emea = await make_group(db, "emea", parent=sales)
    finance = await make_group(db, "finance")
    lead = await actor_with(db, "viewer", member_of=sales, standing="manager")
    stranger = await actor_with(db, "viewer", member_of=finance, standing="manager")

    detail = await admin_for(db).groups.group_detail(lead, emea.id)

    assert detail.path == ["sales", "emea"]
    with pytest.raises(AccessDeniedError):
        await admin_for(db).groups.group_detail(stranger, emea.id)


async def test_group_detail_cross_tenant_is_404(db) -> None:
    actor = await actor_with(db)
    _, other_group = await _other_tenant(db)

    for target in (other_group.id, uuid4()):
        with pytest.raises(NotFoundError):
            await admin_for(db).groups.group_detail(actor, target)


async def test_group_detail_over_http(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")
    growth = await make_group(db, "growth")

    body = (await api.get(f"/api/v1/admin/groups/{growth.id}")).json()

    assert body["path"] == ["growth"]
    assert body["member_count"] == 0
    assert body["grant_count"] == 0
    assert body["parent_id"] is None


# ---- the user list --------------------------------------------------------------


async def test_user_filters_role_status_kind_and_search(db) -> None:
    actor = await actor_with(db)
    await make_user(db, "ana@yougotagift.com", role="analyst")
    await make_user(db, "off@yougotagift.com", status="disabled")
    await make_user(db, "mcp@yougotagift.com", kind="service")
    nina = User(email="nina@yougotagift.com", display_name="Nina Diaz")
    db.add(nina)
    await db.commit()
    admin = admin_for(db)

    async def emails(**filters: str) -> list[str]:
        page = await admin.users.list_users(actor, UserQuery.model_validate(filters))
        return [u.email for u in page.items]

    assert await emails(role="analyst") == ["ana@yougotagift.com"]
    assert await emails(status="disabled") == ["off@yougotagift.com"]
    assert await emails(kind="service") == ["mcp@yougotagift.com"]
    assert await emails(q="  diaz ") == ["nina@yougotagift.com"]
    assert await emails(q="NINA", role="viewer", status="active") == [
        "nina@yougotagift.com"
    ]
    assert await emails(q="nina", role="analyst") == []


async def test_user_cursor_walks_by_email(db) -> None:
    actor = await actor_with(db)
    for name in ("d", "b", "e", "a", "c"):
        await make_user(db, f"{name}-walk@yougotagift.com")
    admin = admin_for(db)

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        query = UserQuery(q="-walk@", limit=2, cursor=cursor)
        page = await admin.users.list_users(actor, query)
        seen.extend(u.email for u in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert seen == [f"{n}-walk@yougotagift.com" for n in "abcde"]
    with pytest.raises(InvalidChangeError, match="page link is invalid"):
        await admin.users.list_users(actor, UserQuery(cursor="!!nope"))


async def test_user_list_over_http(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")
    await make_user(db, "ana@yougotagift.com", role="analyst")

    page = (
        await api.get("/api/v1/admin/users", params={"role": "analyst", "limit": 1})
    ).json()
    assert [u["email"] for u in page["items"]] == ["ana@yougotagift.com"]
    assert page["next_cursor"] is None
    assert "created_at" in page["items"][0]
    for params in (
        {"status": "weird"},
        {"kind": "robot"},
        {"limit": "0"},
        {"limit": "201"},
        {"cursor": "tampered!"},
    ):
        resp = await api.get("/api/v1/admin/users", params=params)
        assert resp.status_code == 422, params


async def test_members_carry_role_and_status(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")
    growth = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com", role="analyst")
    await add_member(db, growth, sara)

    [member] = (await api.get(f"/api/v1/admin/groups/{growth.id}/members")).json()

    assert (member["role"], member["status"]) == ("analyst", "active")

"""What a group manager sees without admin:groups: their groups, and a
narrow lookup of colleagues to add (phase 5, P5-D21, P5-D22)."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.access import Actor
from app.access.errors import AccessDeniedError, InvalidChangeError, NotFoundError
from app.access.models import Group
from app.identity.models import User
from app.main import app as asgi_app
from tests.access_helpers import (
    actor_with,
    add_member,
    admin_for,
    fresh,
    make_group,
    make_user,
)

DEV = "dev@yougotagift.com"
CANDIDATES = "/api/v1/admin/groups/{}/member-candidates"


@pytest_asyncio.fixture
async def api(db) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=asgi_app), base_url="http://test"
    ) as client:
        yield client


# ---- GET /admin/groups for a manager (P5-D22) ---------------------------------


async def test_a_manager_lists_only_their_groups_and_subgroups(db) -> None:
    sales = await make_group(db, "sales")
    await make_group(db, "emea", parent=sales)
    company = await make_group(db, "company")
    team = await make_group(db, "team", parent=company)
    await make_group(db, "finance")
    lead = await actor_with(db, "viewer", member_of=sales, standing="manager")
    team_lead = await actor_with(db, "viewer", member_of=team, standing="manager")

    groups = await admin_for(db).groups.list_groups(lead)
    assert [(g.name, g.parent_id) for g in groups] == [
        ("emea", sales.id),
        ("sales", None),
    ]
    # The real parent_id is kept even when the parent itself isn't listed.
    [only] = await admin_for(db).groups.list_groups(team_lead)
    assert (only.name, only.parent_id) == ("team", company.id)


async def test_a_plain_member_or_viewer_cannot_list_groups(db) -> None:
    sales = await make_group(db, "sales")
    member = await actor_with(db, "viewer", member_of=sales)
    viewer = await actor_with(db, "viewer")

    for actor in (member, viewer):
        with pytest.raises(AccessDeniedError, match="admin:groups"):
            await admin_for(db).groups.list_groups(actor)


async def test_admin_groups_and_the_cli_list_every_tenant_group(db) -> None:
    await make_group(db, "sales")
    await make_group(db, "finance")
    db.add(Group(name="acme-group", tenant="acme"))
    await db.commit()
    admin = await actor_with(db)

    for actor in (admin, Actor.cli()):
        names = [g.name for g in await admin_for(db).groups.list_groups(actor)]
        assert names == ["finance", "sales"]


async def test_manager_group_listing_over_http(api: AsyncClient, db) -> None:
    sales = await make_group(db, "sales")
    await make_group(db, "finance")
    dev = await make_user(db, DEV)
    await add_member(db, sales, dev, "manager")

    resp = await api.get("/api/v1/admin/groups")

    assert resp.status_code == 200
    assert [g["name"] for g in resp.json()] == ["sales"]


# ---- member candidates (P5-D21) ------------------------------------------------


async def _team(db) -> tuple[Group, Actor]:
    sales = await make_group(db, "sales")
    lead = await actor_with(db, "viewer", member_of=sales, standing="manager")
    return sales, lead


async def test_candidates_match_active_humans_not_yet_members(db) -> None:
    sales, lead = await _team(db)
    sara = await make_user(db, "sara.k@yougotagift.com")
    sam = User(email="sam@yougotagift.com", display_name="Sara Morgan")
    db.add(sam)
    await db.commit()
    already = await make_user(db, "sara.member@yougotagift.com")
    await add_member(db, sales, already)
    await make_user(db, "sara.off@yougotagift.com", status="disabled")
    await make_user(db, "sara.bot@yougotagift.com", kind="service")
    db.add(User(email="sara@acme.example", tenant="acme"))
    await db.commit()

    found = await admin_for(db).members.member_candidates(lead, sales.id, "  SARA ")

    assert [(c.email, c.display_name) for c in found] == [
        ("sam@yougotagift.com", "Sara Morgan"),
        ("sara.k@yougotagift.com", ""),
    ]
    assert found[1].user_id == sara.id


async def test_candidates_never_include_the_actor(db) -> None:
    sales = await make_group(db, "sales")
    admin = await actor_with(db)

    found = await admin_for(db).members.member_candidates(admin, sales.id, "admin-")

    assert admin.user_id not in {c.user_id for c in found}


async def test_candidates_are_capped_at_ten(db) -> None:
    sales, lead = await _team(db)
    for i in range(12):
        await make_user(db, f"bulk{i:02}@yougotagift.com")

    found = await admin_for(db).members.member_candidates(lead, sales.id, "bulk")

    assert len(found) == 10
    assert found[0].email == "bulk00@yougotagift.com"


async def test_candidates_need_member_admin_on_that_group(db) -> None:
    sales, _ = await _team(db)
    finance = await make_group(db, "finance")
    other_lead = await actor_with(db, "viewer", member_of=finance, standing="manager")
    viewer = await actor_with(db, "viewer")

    for actor in (other_lead, viewer):
        with pytest.raises(AccessDeniedError):
            await admin_for(db).members.member_candidates(actor, sales.id, "sara")


async def test_candidates_for_a_subgroup_of_a_managed_group(db) -> None:
    sales, lead = await _team(db)
    emea = await make_group(db, "emea", parent=sales)
    await make_user(db, "sara@yougotagift.com")

    lead = await fresh(db, lead)  # a new request sees the new subgroup

    found = await admin_for(db).members.member_candidates(lead, emea.id, "sara")

    assert [c.email for c in found] == ["sara@yougotagift.com"]


async def test_candidates_for_a_cross_tenant_group_are_404(db) -> None:
    admin = await actor_with(db)
    acme = Group(name="acme-group", tenant="acme")
    db.add(acme)
    await db.commit()

    for target in (acme.id, uuid4()):
        with pytest.raises(NotFoundError):
            await admin_for(db).members.member_candidates(admin, target, "sara")


async def test_candidate_query_length_is_3_to_100_after_stripping(db) -> None:
    sales, lead = await _team(db)

    for q in ("", "  ab  ", "x" * 101):
        with pytest.raises(InvalidChangeError):
            await admin_for(db).members.member_candidates(lead, sales.id, q)
    assert await admin_for(db).members.member_candidates(lead, sales.id, " abc ") == []


async def test_candidate_query_is_not_a_wildcard(db) -> None:
    sales, lead = await _team(db)
    await make_user(db, "sara@yougotagift.com")

    assert await admin_for(db).members.member_candidates(lead, sales.id, "%%%") == []


async def test_member_candidates_over_http(api: AsyncClient, db) -> None:
    sales = await make_group(db, "sales")
    dev = await make_user(db, DEV)
    await add_member(db, sales, dev, "manager")
    sara = await make_user(db, "sara@yougotagift.com")
    finance = await make_group(db, "finance")

    ok = await api.get(CANDIDATES.format(sales.id), params={"q": "sara"})
    assert ok.status_code == 200
    assert ok.json() == [
        {"user_id": str(sara.id), "display_name": "", "email": "sara@yougotagift.com"}
    ]
    assert (
        await api.get(CANDIDATES.format(finance.id), params={"q": "sara"})
    ).status_code == 403
    for params in ({}, {"q": "ab"}, {"q": "x" * 101}):
        resp = await api.get(CANDIDATES.format(sales.id), params=params)
        assert resp.status_code == 422, params

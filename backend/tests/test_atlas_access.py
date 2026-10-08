"""Enforcement points 1, 2 and 5 (spec §6): discovery, execution, audit."""

from uuid import uuid4

from sqlmodel import col, select

from app.access import Policy
from app.atlas import AtlasCaller, AtlasTools, ResourcePolicy
from app.models.audit import AtlasAuditLog
from tests.fakes import make_tools

ORDERS_ONLY = ("demo/order/*",)
WEEK = {"start_date": "2026-01-01", "end_date": "2026-01-07"}


async def test_list_metrics_shows_only_allowed_items(db) -> None:
    result = await make_tools(db=db, allowed=ORDERS_ONLY).execute("list_metrics", {})
    demo = result["sources"][0]
    ids = {m["id"] for m in demo["metrics"]}
    assert "revenue" in ids
    assert "new_customers" not in ids
    assert demo["funnels"] == []


async def test_no_grants_means_an_empty_catalog(db) -> None:
    result = await make_tools(db=db, allowed=()).execute("list_metrics", {})
    assert result == {"sources": []}


async def test_search_hides_what_the_caller_cannot_see(db) -> None:
    result = await make_tools(db=db, allowed=ORDERS_ONLY).execute(
        "search_atlas", {"query": "checkout funnel revenue"}
    )
    found = {(r["kind"], r["id"]) for r in result["results"]}
    assert ("metric", "revenue") in found
    assert all(kind != "funnel" for kind, _ in found)


async def test_a_denied_metric_is_refused_and_audited_as_deny(db) -> None:
    user_id = uuid4()
    tools = make_tools(db=db, allowed=("demo/customer/*",), user_id=user_id)

    result = await tools.execute("query_metric", {"metric_id": "revenue", **WEEK})

    assert "isn't available to you" in result["error"]
    row = (
        await db.execute(
            select(AtlasAuditLog).where(col(AtlasAuditLog.user_id) == user_id)
        )
    ).scalar_one()
    assert (row.decision, row.success) == ("deny", False)
    assert row.deny_reason == "not in the test allowlist"
    assert row.auth_method == "test"
    assert row.user_uid == str(user_id)


async def test_breakdowns_comparisons_and_funnels_are_checked(db) -> None:
    tools = make_tools(db=db, allowed=("demo/customer/*",))
    breakdown = await tools.execute(
        "metric_breakdown", {"metric_id": "revenue", **WEEK}
    )
    compare = await tools.execute(
        "compare_periods",
        {
            "metric_id": "revenue",
            "period_a_start": "2026-01-08",
            "period_a_end": "2026-01-14",
            "period_b_start": "2026-01-01",
            "period_b_end": "2026-01-07",
        },
    )
    funnel = await tools.execute(
        "funnel_analyze", {"funnel_id": "checkout_funnel", **WEEK}
    )
    for result in (breakdown, compare, funnel):
        assert "isn't available to you" in result["error"]


async def test_entities_are_visible_through_their_items(db) -> None:
    tools = make_tools(db=db, allowed=("demo/order/revenue",))
    entity = await tools.execute("describe_entity", {"entity_id": "order"})
    assert entity["metrics"] == ["revenue"]
    hidden = await tools.execute("describe_entity", {"entity_id": "customer"})
    assert "isn't available to you" in hidden["error"]


async def test_allowed_calls_are_audited_as_allow(db) -> None:
    user_id = uuid4()
    await make_tools(db=db, user_id=user_id).execute("list_metrics", {})
    row = (
        await db.execute(
            select(AtlasAuditLog).where(col(AtlasAuditLog.user_id) == user_id)
        )
    ).scalar_one()
    assert row.decision == "allow"


async def test_the_real_access_policy_satisfies_the_atlas_contract(db) -> None:
    user_id = uuid4()
    policy: ResourcePolicy = Policy.deny_all(user_id, "yougotagift.com", 1)
    caller = AtlasCaller(user_id=user_id, auth_method="test")
    result = await AtlasTools(caller, policy, db=db).execute("list_metrics", {})
    assert result == {"sources": []}

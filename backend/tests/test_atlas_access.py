"""Enforcement points 1, 2 and 5 (spec §6): discovery, execution, audit."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.access import GrantFacts, Policy, PolicyInputs, UserFacts, evaluate
from app.atlas import AtlasCaller, AtlasRegistry, AtlasTools, ResourcePolicy
from app.atlas.models import EntityDef, FunnelDef, FunnelStepDef, MetricDef
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


# ---- follow-up: search before the limit, policy errors, real policy ------


class ExplodingPolicy:
    """A policy whose evaluation fails (spec §12: fail closed, audit as deny)."""

    def allows(self, resource: str) -> bool:
        raise RuntimeError("policy store unreachable")

    def deny_reason(self, resource: str) -> str:
        raise RuntimeError("policy store unreachable")


@dataclass(frozen=True)
class VerboseDenyPolicy:
    reason: str

    def allows(self, resource: str) -> bool:
        return False

    def deny_reason(self, resource: str) -> str:
        return self.reason


def _tools(policy: ResourcePolicy, db: AsyncSession, user_id: UUID) -> AtlasTools:
    return AtlasTools(AtlasCaller(user_id=user_id, auth_method="test"), policy, db=db)


async def _rows(db: AsyncSession, user_id: UUID) -> list[AtlasAuditLog]:
    result = await db.execute(
        select(AtlasAuditLog).where(col(AtlasAuditLog.user_id) == user_id)
    )
    return list(result.scalars().all())


def _metric(id_: str, name: str) -> MetricDef:
    return MetricDef(id=id_, name=name, entity="e", source="x", query="q")


def _funnel(id_: str) -> FunnelDef:
    step = FunnelStepDef(id="s", name="s", query="q")
    return FunnelDef(id=id_, name=id_, entity="e", source="x", steps=[step])


def _registry(entity: EntityDef) -> AtlasRegistry:
    registry = AtlasRegistry(plugins={})
    registry.entities = {entity.id: entity}
    registry.metrics = {m.id: m for m in entity.metrics}
    registry.funnels = {f.id: f for f in entity.funnels}
    return registry


async def test_search_filters_before_the_limit() -> None:
    # More high-scoring denied matches than any search pool or limit.
    loud = [_metric(f"loud_{i}", "alpha beta") for i in range(60)]
    quiet = _metric("quiet", "alpha")
    entity = EntityDef(id="e", name="zzz", source="x", metrics=[*loud, quiet])
    tools = make_tools(registry=_registry(entity), allowed=("x/e/quiet",))

    result = await tools.execute("search_atlas", {"query": "alpha beta"})

    assert [(r["kind"], r["id"]) for r in result["results"]] == [("metric", "quiet")]


async def test_a_failing_policy_denies_execution_and_is_audited(db) -> None:
    user_id = uuid4()
    tools = _tools(ExplodingPolicy(), db, user_id)

    result = await tools.execute("query_metric", {"metric_id": "revenue", **WEEK})

    # A policy-evaluation failure is not the same claim as a real denial: it
    # gets its own honest message, never "isn't available to you".
    assert "couldn't be checked against your access right now" in result["error"]
    [row] = await _rows(db, user_id)
    assert (row.decision, row.success) == ("deny", False)
    assert row.deny_reason == "the access check failed"


async def test_a_failing_policy_hides_the_catalog(db) -> None:
    result = await _tools(ExplodingPolicy(), db, uuid4()).execute("list_metrics", {})
    assert result == {"sources": []}


async def test_a_failing_policy_denies_describe_entity(db) -> None:
    user_id = uuid4()
    tools = _tools(ExplodingPolicy(), db, user_id)
    result = await tools.execute("describe_entity", {"entity_id": "order"})
    assert "isn't available to you" in result["error"]
    [row] = await _rows(db, user_id)
    assert row.deny_reason == "the access check failed"


async def test_unknown_tools_are_audited_as_deny(db) -> None:
    user_id = uuid4()
    result = await make_tools(db=db, user_id=user_id).execute("run_sql", {"sql": "1"})
    assert "error" in result
    [row] = await _rows(db, user_id)
    assert (row.tool, row.success, row.decision) == ("run_sql", False, "deny")
    assert row.deny_reason == "unknown tool"


async def test_deny_reason_is_truncated_to_200_characters(db) -> None:
    user_id = uuid4()
    tools = _tools(VerboseDenyPolicy("x" * 300), db, user_id)
    await tools.execute("query_metric", {"metric_id": "revenue", **WEEK})
    [row] = await _rows(db, user_id)
    assert row.deny_reason == "x" * 200


async def test_an_entity_is_visible_through_its_funnel_grant(db) -> None:
    tools = make_tools(db=db, allowed=("demo/checkout/checkout_funnel",))
    entity = await tools.execute("describe_entity", {"entity_id": "checkout"})
    assert entity["funnels"] == ["checkout_funnel"]
    assert entity["metrics"] == []
    hidden = await tools.execute("describe_entity", {"entity_id": "order"})
    assert "isn't available to you" in hidden["error"]


async def test_an_entity_is_visible_through_an_entity_level_grant(db) -> None:
    # Exercises `_entity_visible` in isolation via an exact-path test policy
    # (StaticPolicy + make_tools' `allowed`): the pattern "demo/order" matches
    # only the entity path itself, never its items. Production can't store this
    # as a grant — `validate_pattern` requires "demo/order/*" to cover an entity,
    # which also covers its items.
    tools = make_tools(db=db, allowed=("demo/order",))
    entity = await tools.execute("describe_entity", {"entity_id": "order"})
    assert entity["id"] == "order"
    assert entity["metrics"] == []  # the entity grant does not cover its items
    denied = await tools.execute("query_metric", {"metric_id": "revenue", **WEEK})
    assert "isn't available to you" in denied["error"]


async def test_describe_entity_filters_its_funnels() -> None:
    entity = EntityDef(
        id="e", name="E", source="x", funnels=[_funnel("f_ok"), _funnel("f_no")]
    )
    tools = make_tools(registry=_registry(entity), allowed=("x/e/f_ok",))
    result = await tools.execute("describe_entity", {"entity_id": "e"})
    assert result["funnels"] == ["f_ok"]


async def test_search_returns_allowed_entities(db) -> None:
    tools = make_tools(db=db, allowed=("demo/customer/*",))
    result = await tools.execute("search_atlas", {"query": "customer order"})
    found = {(r["kind"], r["id"]) for r in result["results"]}
    assert ("entity", "customer") in found
    assert ("entity", "order") not in found


async def test_compare_periods_on_a_denied_metric_writes_one_deny_row(db) -> None:
    user_id = uuid4()
    tools = make_tools(db=db, allowed=("demo/customer/*",), user_id=user_id)
    await tools.execute(
        "compare_periods",
        {
            "metric_id": "revenue",
            "period_a_start": "2026-01-08",
            "period_a_end": "2026-01-14",
            "period_b_start": "2026-01-01",
            "period_b_end": "2026-01-07",
        },
    )
    rows = await _rows(db, user_id)
    assert [(r.tool, r.decision) for r in rows] == [("compare_periods", "deny")]


def _grant(user_id: UUID, effect: str, target: str) -> GrantFacts:
    return GrantFacts(
        id=uuid4(),
        subject_type="user",
        subject_id=user_id,
        effect=effect,
        target_kind="resource",
        target=target,
        expires_at=None,
    )


async def test_a_real_access_policy_denies_orders_and_allows_customers(db) -> None:
    user_id = uuid4()
    inputs = PolicyInputs(
        user=UserFacts(id=user_id, role="viewer", status="active", tenant="ygg"),
        groups={},
        memberships={},
        grants=[
            _grant(user_id, "allow", "demo/*"),
            _grant(user_id, "deny", "demo/order/*"),
        ],
        policy_version=1,
    )
    policy: ResourcePolicy = evaluate(inputs, datetime.now(UTC))
    tools = _tools(policy, db, user_id)

    revenue: dict[str, Any] = await tools.execute(
        "query_metric", {"metric_id": "revenue", **WEEK}
    )
    customers = await tools.execute("query_metric", {"metric_id": "customers_total"})

    assert "isn't available to you" in revenue["error"]
    assert "error" not in customers
    assert customers["metric_id"] == "customers_total"
    decisions = {r.decision for r in await _rows(db, user_id)}
    assert decisions == {"allow", "deny"}

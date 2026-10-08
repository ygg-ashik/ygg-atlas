from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.atlas import AtlasRegistry, AtlasTools
from app.atlas.models import MetricDef
from app.insights.service import InsightsService

PROV = {
    "tool": "query_metric",
    "source": "demo",
    "metric_id": "tasks_open",
    "metric_name": "Tasks Open",
    "freshness": None,
    "executed_at": "t",
}


class ScriptedTools(AtlasTools):
    """AtlasTools with a fixed registry and canned results per tool name."""

    def __init__(
        self, metrics: list[MetricDef], results: dict[str, dict[str, Any]]
    ) -> None:
        registry = AtlasRegistry(plugins={})
        registry.metrics = {m.id: m for m in metrics}
        super().__init__(user_uid="u", surface="api", registry=registry)
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, arguments))
        return self.results[tool]


def _metric(id_: str, scope: str = "range", breakdown: str | None = None) -> MetricDef:
    return MetricDef(
        id=id_, name=id_, time_scope=scope, query="q", breakdown_query=breakdown
    )


async def test_overview_over_seeded_demo_data(db: AsyncSession) -> None:
    service = InsightsService(AtlasTools(user_uid="u", surface="api"))
    overview = await service.overview(7, datetime.now(UTC).date())
    revenue = next(k for k in overview.kpis if k.metric_id == "revenue")
    assert revenue.value == 10500.0
    assert revenue.previous == 4500.0  # seed covers 3 days of the previous window
    assert overview.breakdown is not None
    assert overview.breakdown.rows


async def test_catalog_validates_list_metrics(db: AsyncSession) -> None:
    catalog = await InsightsService(AtlasTools(user_uid="u")).catalog()
    assert any(s.id == "demo" for s in catalog.sources)


async def test_snapshot_kpi_uses_query_metric_and_breakdown_has_no_dates() -> None:
    tools = ScriptedTools(
        [_metric("tasks_open", scope="snapshot", breakdown="b")],
        {
            "query_metric": {"name": "Tasks Open", "value": 7.0, "provenance": [PROV]},
            "metric_breakdown": {
                "name": "Tasks Open",
                "unit": "",
                "rows": [{"label": "Sam", "value": 4.0}],
                "provenance": [PROV],
            },
        },
    )
    overview = await InsightsService(tools).overview(30, date(2026, 10, 8))
    assert [k.metric_id for k in overview.kpis] == ["tasks_open"]
    assert overview.kpis[0].previous is None
    assert overview.breakdown is not None
    assert tools.calls == [
        ("query_metric", {"metric_id": "tasks_open"}),
        ("metric_breakdown", {"metric_id": "tasks_open", "limit": 5}),
    ]


async def test_failed_tools_are_left_out() -> None:
    tools = ScriptedTools(
        [_metric("revenue", breakdown="b")],
        {"compare_periods": {"error": "x"}, "metric_breakdown": {"error": "x"}},
    )
    overview = await InsightsService(tools).overview(7, date(2026, 10, 8))
    assert overview.kpis == []
    assert overview.breakdown is None


async def test_no_breakdown_metric_means_no_breakdown_call() -> None:
    tools = ScriptedTools([_metric("revenue")], {"compare_periods": {"error": "x"}})
    overview = await InsightsService(tools).overview(7, date(2026, 10, 8))
    assert overview.breakdown is None
    assert [c[0] for c in tools.calls] == ["compare_periods"]

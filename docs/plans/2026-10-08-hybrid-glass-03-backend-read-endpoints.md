# Hybrid Glass Track E-be: Backend Read Endpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Follow the `engineering-standards` skill before writing code and the `production-code-review` skill before calling the track done. Gate: `make check` from the repo root.

**Goal:** Add two read-only, audited endpoints: `GET /api/v1/atlas/metrics` (catalog for the Metrics page and ⌘K) and `GET /api/v1/atlas/overview?days=` (KPIs + one top-N breakdown for the dashboard).

**Architecture:** A new vertical-slice module `app/insights` (ARCHITECTURE.md §2.2):
- `router.py` is thin.
- `service.py` holds the use cases.
- `schemas.py` holds the response shapes.
- `selection.py` holds the pure metric/window selection helpers.

There's no `repository.py`: the module doesn't touch the database. Every number comes through `AtlasTools.execute(...)` with `surface="api"`, so it is audited (guardrail #5) and carries provenance (guardrail #2). The module only chooses governed metrics and date windows. There's no SQL here (guardrail #1). Range KPIs use `compare_periods` (current window vs the previous window of equal length, full UTC days ending yesterday). Snapshot KPIs use `query_metric`. The module sits in the edge layer next to `app.api` and `app.mcp`, and the import-linter contracts are updated in the same change.

**Tech Stack:** FastAPI, Pydantic, pytest + httpx ASGI, sqlite demo seed, import-linter, pyright (strict for this module).

**Branch/worktree:** `feature/hybrid-glass-e-be` · backend commands from `backend/`.

**Contract:** `docs/plans/2026-10-08-hybrid-glass-00-overview.md` § Shared contracts 2 (exact field names).

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `app/insights/__init__.py` | Create | Public interface: `router` |
| `app/insights/selection.py` (+ `tests/test_insights_selection.py`) | Create | Pure: date windows, KPI/breakdown metric choice, result shaping |
| `app/insights/schemas.py` | Create | Pydantic response models (contract §2) |
| `app/insights/service.py` | Create | `InsightsService.catalog()` / `.overview(days, today)` over `AtlasTools` |
| `app/insights/router.py` (+ `tests/test_insights_api.py`) | Create | Thin routes + service dependency |
| `app/main.py` | Modify | `include_router` |
| `pyproject.toml`, `../ARCHITECTURE.md` | Modify | import-linter contracts, pyright strict list, layer diagram |

---

### Task 1: Pure selection helpers

**Files:** Create `app/insights/__init__.py` (empty docstring for now), `app/insights/selection.py`, `tests/test_insights_selection.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_insights_selection.py
from datetime import date

from app.atlas.models import MetricDef
from app.insights.selection import (
    PREFERRED_KPIS,
    kpi_from_compare,
    kpi_from_query,
    pick_breakdown_metric,
    pick_kpi_metrics,
    windows,
)


def _m(
    id_: str, scope: str = "range", breakdown: str | None = None, good: str = "up"
) -> MetricDef:
    return MetricDef(
        id=id_,
        name=id_.title(),
        unit="AED",
        time_scope=scope,
        query="select 1",
        breakdown_query=breakdown,
        good_direction=good,
        source="demo",
        entity="order",
    )


PROV = {
    "tool": "compare_periods",
    "source": "demo",
    "metric_id": "revenue",
    "metric_name": "Revenue",
    "freshness": None,
    "executed_at": "t",
}


def test_windows_are_full_days_ending_yesterday() -> None:
    cur, prev = windows(days=7, today=date(2026, 10, 8))
    assert cur == ("2026-10-01", "2026-10-07")
    assert prev == ("2026-09-24", "2026-09-30")


def test_pick_kpi_metrics_prefers_known_order_and_caps_at_four() -> None:
    ids = ["aov", "revenue", "orders_count", "b2b_revenue", "new_customers", "zzz"]
    metrics = {i: _m(i) for i in ids}
    picked = pick_kpi_metrics(metrics)
    assert [m.id for m in picked] == ["revenue", "orders_count", "aov", "b2b_revenue"]


def test_pick_kpi_metrics_fills_from_other_metrics() -> None:
    metrics = {"leads_total": _m("leads_total"), "tasks_open": _m("tasks_open", "snapshot")}
    assert [m.id for m in pick_kpi_metrics(metrics)] == ["leads_total", "tasks_open"]


def test_pick_breakdown_metric_needs_a_breakdown_query() -> None:
    metrics = {"orders_count": _m("orders_count"), "revenue": _m("revenue", breakdown="q")}
    picked = pick_breakdown_metric(metrics)
    assert picked is not None and picked.id == "revenue"
    assert pick_breakdown_metric({"x": _m("x")}) is None


def test_kpi_from_compare() -> None:
    result = {
        "name": "Revenue",
        "unit": "AED",
        "period_a": {"value": 120.0},
        "period_b": {"value": 100.0},
        "delta_pct": 20.0,
        "provenance": [PROV],
    }
    assert kpi_from_compare(_m("revenue"), result) == {
        "metric_id": "revenue",
        "name": "Revenue",
        "unit": "AED",
        "value": 120.0,
        "previous": 100.0,
        "delta_pct": 20.0,
        "good_direction": "up",
        "provenance": PROV,
    }


def test_kpi_from_query_snapshot_has_no_previous() -> None:
    result = {"name": "Tasks Open", "unit": "", "value": 7.0, "provenance": [PROV]}
    kpi = kpi_from_query(_m("tasks_open", scope="snapshot", good="down"), result)
    assert kpi is not None
    assert kpi["previous"] is None and kpi["delta_pct"] is None
    assert kpi["good_direction"] == "down"


def test_error_results_are_skipped() -> None:
    assert kpi_from_compare(_m("revenue"), {"error": "x"}) is None
    assert kpi_from_query(_m("revenue"), {"error": "x"}) is None


def test_preferred_list_is_stable() -> None:
    assert PREFERRED_KPIS[:4] == ["revenue", "orders_count", "aov", "b2b_revenue"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_insights_selection.py -v` → FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `app/insights/selection.py`**

```python
"""Which governed metrics and windows the overview shows. Pure: no I/O, no SQL."""

from datetime import date, timedelta
from typing import Any

from app.atlas.models import MetricDef

PREFERRED_KPIS = ["revenue", "orders_count", "aov", "b2b_revenue", "new_customers"]
MAX_KPIS = 4
ALLOWED_DAYS = (7, 30, 90)

Window = tuple[str, str]


def windows(days: int, today: date) -> tuple[Window, Window]:
    """Current = last `days` full UTC days ending yesterday; previous = the one before."""
    end = today - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    current = (start.isoformat(), end.isoformat())
    previous = (prev_start.isoformat(), prev_end.isoformat())
    return current, previous


def _ordered(metrics: dict[str, MetricDef]) -> list[MetricDef]:
    preferred = [metrics[mid] for mid in PREFERRED_KPIS if mid in metrics]
    rest = [metrics[mid] for mid in sorted(metrics) if mid not in PREFERRED_KPIS]
    return preferred + rest


def pick_kpi_metrics(metrics: dict[str, MetricDef]) -> list[MetricDef]:
    return _ordered(metrics)[:MAX_KPIS]


def pick_breakdown_metric(metrics: dict[str, MetricDef]) -> MetricDef | None:
    return next((m for m in _ordered(metrics) if m.breakdown_query), None)


def first_provenance(result: dict[str, Any]) -> dict[str, Any] | None:
    prov = result.get("provenance") or []
    return prov[0] if prov else None


def _kpi(
    metric: MetricDef, result: dict[str, Any], value: float, previous: float | None
) -> dict[str, Any]:
    return {
        "metric_id": metric.id,
        "name": result.get("name", metric.name),
        "unit": result.get("unit", metric.unit),
        "value": value,
        "previous": previous,
        "delta_pct": result.get("delta_pct"),
        "good_direction": metric.good_direction,
        "provenance": first_provenance(result),
    }


def kpi_from_compare(metric: MetricDef, result: dict[str, Any]) -> dict[str, Any] | None:
    if "error" in result or first_provenance(result) is None:
        return None
    return _kpi(metric, result, result["period_a"]["value"], result["period_b"]["value"])


def kpi_from_query(metric: MetricDef, result: dict[str, Any]) -> dict[str, Any] | None:
    if "error" in result or first_provenance(result) is None:
        return None
    return _kpi(metric, result, result["value"], None)
```

- [ ] **Step 4: Run tests + types**

Run: `uv run pytest tests/test_insights_selection.py -v && uv run pyright app/insights tests/test_insights_selection.py`
Expected: PASS, 0 errors.

- [ ] **Step 5: Commit**

```bash
git add app/insights tests/test_insights_selection.py
git commit -m "feat(insights): overview metric and window selection"
```

---

### Task 2: Schemas, service, router, wiring, contracts

**Files:** Create `app/insights/schemas.py`, `app/insights/service.py`, `app/insights/router.py`, `tests/test_insights_api.py`; Modify `app/insights/__init__.py`, `app/main.py`, `pyproject.toml`, `../ARCHITECTURE.md`

- [ ] **Step 1: Write failing API tests**

```python
# tests/test_insights_api.py
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select


@pytest_asyncio.fixture
async def api(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_metrics_catalog_lists_governed_metrics(api: AsyncClient) -> None:
    body = (await api.get("/api/v1/atlas/metrics")).json()
    demo = next(s for s in body["sources"] if s["id"] == "demo")
    assert {"revenue", "orders_count"} <= {m["id"] for m in demo["metrics"]}
    revenue = next(m for m in demo["metrics"] if m["id"] == "revenue")
    expected = {"id", "name", "description", "unit", "time_scope", "has_breakdown", "entity"}
    assert expected <= set(revenue)
    assert any(f["id"] == "checkout_funnel" for f in demo["funnels"])


async def test_overview_kpis_carry_provenance(api: AsyncClient) -> None:
    body = (await api.get("/api/v1/atlas/overview?days=7")).json()
    assert body["days"] == 7
    assert body["start_date"] < body["end_date"]
    kpis = {k["metric_id"]: k for k in body["kpis"]}
    assert kpis["revenue"]["value"] == 10500.0  # seed: 1500 AED/day x 7 full days
    assert kpis["revenue"]["provenance"]["source"] == "demo"
    assert body["breakdown"]["metric_id"] == "revenue"
    assert body["breakdown"]["rows"]


async def test_overview_rejects_unsupported_windows(api: AsyncClient) -> None:
    resp = await api.get("/api/v1/atlas/overview?days=13")
    assert resp.status_code == 422


async def test_overview_is_audited_on_the_api_surface(
    api: AsyncClient, db: AsyncSession
) -> None:
    from app.models.audit import AtlasAuditLog

    await api.get("/api/v1/atlas/overview?days=7")
    rows = (await db.execute(select(AtlasAuditLog))).scalars().all()
    assert rows and all(r.surface == "api" for r in rows)
```

First check the audit model's field names: `grep -n "surface" app/models/audit.py`. If the field differs, adjust the attribute in the last test.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_insights_api.py -v` → FAIL (404s)

- [ ] **Step 3: Implement schemas** (`app/insights/schemas.py`, contract §2 verbatim)

```python
"""Response shapes for the insights endpoints (contract §2)."""

from typing import Literal

from pydantic import BaseModel


class ProvenanceOut(BaseModel):
    tool: str
    source: str
    metric_id: str | None = None
    metric_name: str | None = None
    freshness: str | None = None
    executed_at: str


class CatalogMetric(BaseModel):
    id: str
    name: str
    description: str
    unit: str
    time_scope: Literal["range", "snapshot"]
    has_breakdown: bool
    entity: str


class CatalogFunnel(BaseModel):
    id: str
    name: str
    description: str
    entity: str


class CatalogSource(BaseModel):
    id: str
    name: str
    description: str
    metrics: list[CatalogMetric]
    funnels: list[CatalogFunnel]


class MetricsCatalog(BaseModel):
    sources: list[CatalogSource]


class OverviewKpi(BaseModel):
    metric_id: str
    name: str
    unit: str
    value: float
    previous: float | None
    delta_pct: float | None
    good_direction: Literal["up", "down"]
    provenance: ProvenanceOut


class BreakdownRow(BaseModel):
    label: str
    value: float


class OverviewBreakdown(BaseModel):
    metric_id: str
    name: str
    unit: str
    rows: list[BreakdownRow]
    provenance: ProvenanceOut


class Overview(BaseModel):
    days: int
    start_date: str
    end_date: str
    kpis: list[OverviewKpi]
    breakdown: OverviewBreakdown | None
```

- [ ] **Step 4: Implement the service** (`app/insights/service.py`)

```python
"""Insights use cases: the catalog and the dashboard overview.

All numbers come from AtlasTools (audited, provenance-bearing). No SQL, no FastAPI.
"""

from datetime import date
from typing import Any

from app.atlas import AtlasTools
from app.atlas.models import MetricDef
from app.insights.schemas import MetricsCatalog, Overview
from app.insights.selection import (
    Window,
    first_provenance,
    kpi_from_compare,
    kpi_from_query,
    pick_breakdown_metric,
    pick_kpi_metrics,
    windows,
)

BREAKDOWN_LIMIT = 5


class InsightsService:
    def __init__(self, tools: AtlasTools) -> None:
        self._tools = tools

    async def catalog(self) -> MetricsCatalog:
        result = await self._tools.execute("list_metrics", {})
        return MetricsCatalog.model_validate(result)

    async def overview(self, days: int, today: date) -> Overview:
        current, previous = windows(days, today)
        metrics = self._tools.registry.metrics
        kpis: list[dict[str, Any]] = []
        for metric in pick_kpi_metrics(metrics):
            kpi = await self._kpi(metric, current, previous)
            if kpi is not None:
                kpis.append(kpi)
        breakdown = await self._breakdown(pick_breakdown_metric(metrics), current)
        return Overview.model_validate(
            {
                "days": days,
                "start_date": current[0],
                "end_date": current[1],
                "kpis": kpis,
                "breakdown": breakdown,
            }
        )

    async def _kpi(
        self, metric: MetricDef, current: Window, previous: Window
    ) -> dict[str, Any] | None:
        if metric.time_scope == "snapshot":
            result = await self._tools.execute("query_metric", {"metric_id": metric.id})
            return kpi_from_query(metric, result)
        result = await self._tools.execute(
            "compare_periods",
            {
                "metric_id": metric.id,
                "period_a_start": current[0],
                "period_a_end": current[1],
                "period_b_start": previous[0],
                "period_b_end": previous[1],
            },
        )
        return kpi_from_compare(metric, result)

    async def _breakdown(
        self, metric: MetricDef | None, current: Window
    ) -> dict[str, Any] | None:
        if metric is None:
            return None
        args: dict[str, Any] = {"metric_id": metric.id, "limit": BREAKDOWN_LIMIT}
        if metric.time_scope == "range":
            args |= {"start_date": current[0], "end_date": current[1]}
        result = await self._tools.execute("metric_breakdown", args)
        provenance = first_provenance(result)
        if "error" in result or provenance is None:
            return None
        return {
            "metric_id": metric.id,
            "name": result["name"],
            "unit": result["unit"],
            "rows": result["rows"],
            "provenance": provenance,
        }
```

- [ ] **Step 5: Implement the thin router + public interface**

```python
# app/insights/router.py
"""Thin HTTP edge for insights: parse → service → schema."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.atlas import AtlasTools
from app.database import get_db
from app.insights.schemas import MetricsCatalog, Overview
from app.insights.selection import ALLOWED_DAYS
from app.insights.service import InsightsService
from app.middleware import AuthUser, get_current_user

router = APIRouter(prefix="/api/v1/atlas", tags=["insights"])


def get_insights_service(
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InsightsService:
    # Scope comes from the token (guardrail #4); every call is audited as "api".
    return InsightsService(AtlasTools(user_uid=user.uid, surface="api", db=db))


@router.get("/metrics", response_model=MetricsCatalog)
async def metrics_catalog(
    service: InsightsService = Depends(get_insights_service),
) -> MetricsCatalog:
    return await service.catalog()


@router.get("/overview", response_model=Overview)
async def overview(
    days: int = Query(30),
    service: InsightsService = Depends(get_insights_service),
) -> Overview:
    if days not in ALLOWED_DAYS:
        raise HTTPException(status_code=422, detail=f"days must be one of {list(ALLOWED_DAYS)}")
    return await service.overview(days, datetime.now(UTC).date())
```

The router passes the `AsyncSession` straight to `AtlasTools` (its audit writer). It never imports a repository or `sqlmodel`, so it complies with §2.2.

```python
# app/insights/__init__.py
"""Insights: governed catalog + dashboard overview (read-only, audited)."""

from app.insights.router import router

__all__ = ["router"]
```

`app/main.py`: add `from app.insights import router as insights_router` and `app.include_router(insights_router)` after the chat router. (Use the same `get_db` dependency `app/api/chat.py` uses if its import path changed.)

- [ ] **Step 6: Update contracts and architecture doc**

In `pyproject.toml`:
- Layers contract: `"app.api | app.mcp",` → `"app.api | app.mcp | app.insights",`, and rename to `"Backend layers: main > api|mcp|insights > agent > atlas > sources"`.
- "Source plugins are leaves": add `"app.insights"` to `forbidden_modules`.
- "Platform modules never depend on features": add `"app.insights"` to `forbidden_modules`.
- `[tool.pyright]` › `strict = ["app/insights"]`.

In `../ARCHITECTURE.md` §2.1: change the `app.api | app.mcp` diagram line to `app.api | app.mcp | app.insights   edges (thin) + read-only insights`, and mention `app.insights` in the "api and mcp are siblings" rule row.

- [ ] **Step 7: Run module tests + full gate**

Run: `uv run pytest tests/test_insights_api.py tests/test_insights_selection.py -v` → PASS.
If `revenue` ≠ 10500, check the window (7 full days ending yesterday) against the conftest seed (1500/day for 10 days). Fix the code, not the assertion.

From the repo root: `make check` → green (ruff 88, pyright incl. strict `app/insights`, import-linter, pytest ≥80%).

- [ ] **Step 8: Commit**

```bash
git add app/insights app/main.py tests/test_insights_api.py pyproject.toml ../ARCHITECTURE.md
git commit -m "feat(insights): audited metrics catalog and dashboard overview endpoints"
```

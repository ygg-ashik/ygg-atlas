# Hybrid Glass Track E-be: Backend Read Endpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two read-only, audited endpoints: `GET /api/v1/atlas/metrics` (catalog for the Metrics page and ⌘K) and `GET /api/v1/atlas/overview?days=` (KPIs + one top-N breakdown for the dashboard).

**Architecture:** A new `app/api/atlas.py` router. Every number goes through `AtlasTools.execute(...)` with `surface="api"`, so it is audited (guardrail #5) and carries provenance (guardrail #2). The router only *chooses* governed metrics and date ranges. No SQL here (guardrail #1). Range KPIs use `compare_periods` (current window vs the previous window of equal length, both ending yesterday, full UTC days). Snapshot KPIs use `query_metric`.

**Tech Stack:** FastAPI, pytest + httpx ASGI, sqlite demo seed.

**Branch/worktree:** `feature/hybrid-glass-e-be` · from `backend/`.

**Contract:** `docs/plans/2026-10-08-hybrid-glass-00-overview.md` § Shared contracts 2 (exact field names).

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `app/api/overview.py` (+ `tests/test_overview.py`) | Create | Pure helpers: date windows, KPI selection, KPI/breakdown shaping |
| `app/api/atlas.py` (+ `tests/test_atlas_api.py`) | Create | Router: `/metrics`, `/overview` |
| `app/api/__init__.py`, `app/main.py` | Modify | Register router |

---

### Task 1: Pure overview helpers

**Files:** Create `app/api/overview.py`, `tests/test_overview.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_overview.py
from datetime import date

from app.api.overview import (
    PREFERRED_KPIS,
    kpi_from_compare,
    kpi_from_query,
    pick_breakdown_metric,
    pick_kpi_metrics,
    windows,
)
from app.atlas.models import MetricDef


def _m(id_, scope="range", breakdown=None, good="up"):
    return MetricDef(id=id_, name=id_.title(), unit="AED", time_scope=scope, query="select 1",
                     breakdown_query=breakdown, good_direction=good, source="demo", entity="order")


def test_windows_are_full_days_ending_yesterday():
    cur, prev = windows(days=7, today=date(2026, 10, 8))
    assert cur == ("2026-10-01", "2026-10-07")
    assert prev == ("2026-09-24", "2026-09-30")


def test_pick_kpi_metrics_prefers_known_order_and_caps_at_four():
    metrics = {m.id: m for m in [_m("aov"), _m("revenue"), _m("orders_count"), _m("b2b_revenue"),
                                 _m("new_customers"), _m("zzz")]}
    picked = pick_kpi_metrics(metrics)
    assert [m.id for m in picked] == ["revenue", "orders_count", "aov", "b2b_revenue"]


def test_pick_kpi_metrics_fills_from_other_metrics_when_preferred_missing():
    metrics = {m.id: m for m in [_m("leads_total"), _m("tasks_open", scope="snapshot")]}
    assert [m.id for m in pick_kpi_metrics(metrics)] == ["leads_total", "tasks_open"]


def test_pick_breakdown_metric_needs_a_breakdown_query():
    metrics = {m.id: m for m in [_m("orders_count"), _m("revenue", breakdown="select 1")]}
    assert pick_breakdown_metric(metrics).id == "revenue"
    assert pick_breakdown_metric({"x": _m("x")}) is None


PROV = {"tool": "compare_periods", "source": "demo", "metric_id": "revenue", "metric_name": "Revenue",
        "freshness": None, "executed_at": "t"}


def test_kpi_from_compare():
    result = {"metric_id": "revenue", "name": "Revenue", "unit": "AED",
              "period_a": {"value": 120.0}, "period_b": {"value": 100.0}, "delta_pct": 20.0,
              "provenance": [PROV]}
    assert kpi_from_compare(_m("revenue"), result) == {
        "metric_id": "revenue", "name": "Revenue", "unit": "AED", "value": 120.0, "previous": 100.0,
        "delta_pct": 20.0, "good_direction": "up", "provenance": PROV}


def test_kpi_from_query_snapshot_has_no_previous():
    result = {"metric_id": "tasks_open", "name": "Tasks Open", "unit": "", "value": 7.0, "provenance": [PROV]}
    kpi = kpi_from_query(_m("tasks_open", scope="snapshot", good="down"), result)
    assert kpi["previous"] is None and kpi["delta_pct"] is None and kpi["good_direction"] == "down"


def test_error_results_are_skipped():
    assert kpi_from_compare(_m("revenue"), {"error": "x"}) is None
    assert kpi_from_query(_m("revenue"), {"error": "x"}) is None


def test_preferred_list_is_stable():
    assert PREFERRED_KPIS[:4] == ["revenue", "orders_count", "aov", "b2b_revenue"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_overview.py -v`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement `app/api/overview.py`**

```python
"""Pure helpers for the dashboard overview: which governed metrics, which windows.

No SQL and no data access. Numbers come only from AtlasTools results (audited).
"""

from datetime import date, timedelta

from app.atlas.models import MetricDef

PREFERRED_KPIS = ["revenue", "orders_count", "aov", "b2b_revenue", "new_customers"]
MAX_KPIS = 4
ALLOWED_DAYS = (7, 30, 90)


def windows(days: int, today: date) -> tuple[tuple[str, str], tuple[str, str]]:
    """Current = last `days` full UTC days ending yesterday; previous = the window before it."""
    end = today - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return (start.isoformat(), end.isoformat()), (prev_start.isoformat(), prev_end.isoformat())


def pick_kpi_metrics(metrics: dict[str, MetricDef]) -> list[MetricDef]:
    picked = [metrics[mid] for mid in PREFERRED_KPIS if mid in metrics]
    for mid in sorted(metrics):
        if len(picked) >= MAX_KPIS:
            break
        if metrics[mid] not in picked:
            picked.append(metrics[mid])
    return picked[:MAX_KPIS]


def pick_breakdown_metric(metrics: dict[str, MetricDef]) -> MetricDef | None:
    ordered = [metrics[m] for m in PREFERRED_KPIS if m in metrics] + [
        metrics[m] for m in sorted(metrics) if m not in PREFERRED_KPIS
    ]
    return next((m for m in ordered if m.breakdown_query), None)


def _prov(result: dict) -> dict | None:
    prov = result.get("provenance") or []
    return prov[0] if prov else None


def kpi_from_compare(metric: MetricDef, result: dict) -> dict | None:
    if "error" in result or _prov(result) is None:
        return None
    return {
        "metric_id": metric.id,
        "name": result.get("name", metric.name),
        "unit": result.get("unit", metric.unit),
        "value": result["period_a"]["value"],
        "previous": result["period_b"]["value"],
        "delta_pct": result.get("delta_pct"),
        "good_direction": metric.good_direction,
        "provenance": _prov(result),
    }


def kpi_from_query(metric: MetricDef, result: dict) -> dict | None:
    if "error" in result or _prov(result) is None:
        return None
    return {
        "metric_id": metric.id,
        "name": result.get("name", metric.name),
        "unit": result.get("unit", metric.unit),
        "value": result["value"],
        "previous": None,
        "delta_pct": None,
        "good_direction": metric.good_direction,
        "provenance": _prov(result),
    }
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_overview.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/overview.py tests/test_overview.py
git commit -m "feat(api): overview metric selection + KPI shaping helpers"
```

---

### Task 2: `/api/v1/atlas` router

**Files:** Create `app/api/atlas.py`, `tests/test_atlas_api.py`; Modify `app/api/__init__.py`, `app/main.py`

- [ ] **Step 1: Write failing API tests**

```python
# tests/test_atlas_api.py
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlmodel import select


@pytest_asyncio.fixture
async def api(db):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_metrics_catalog_lists_governed_metrics(api):
    body = (await api.get("/api/v1/atlas/metrics")).json()
    demo = next(s for s in body["sources"] if s["id"] == "demo")
    ids = {m["id"] for m in demo["metrics"]}
    assert {"revenue", "orders_count"} <= ids
    revenue = next(m for m in demo["metrics"] if m["id"] == "revenue")
    assert set(revenue) >= {"id", "name", "description", "unit", "time_scope", "has_breakdown", "entity"}
    assert any(f["id"] == "checkout_funnel" for f in demo["funnels"])


async def test_overview_returns_kpis_with_provenance_and_breakdown(api):
    body = (await api.get("/api/v1/atlas/overview?days=7")).json()
    assert body["days"] == 7
    assert body["start_date"] < body["end_date"]
    kpis = {k["metric_id"]: k for k in body["kpis"]}
    assert kpis["revenue"]["value"] == 10500.0  # seed: 1500 AED/day × 7 full days
    assert kpis["revenue"]["provenance"]["source"] == "demo"
    assert body["breakdown"]["metric_id"] == "revenue"
    assert body["breakdown"]["rows"]


async def test_overview_rejects_unsupported_windows(api):
    resp = await api.get("/api/v1/atlas/overview?days=13")
    assert resp.status_code == 422


async def test_overview_is_audited_on_the_api_surface(api, db):
    from app.models.audit import AtlasAuditLog

    await api.get("/api/v1/atlas/overview?days=7")
    rows = (await db.execute(select(AtlasAuditLog))).scalars().all()
    assert rows and all(r.surface == "api" for r in rows)
```

Check the audit model's attribute names first: `grep -n "surface\|tool" app/models/audit.py`. Adjust `r.surface` if the column is named differently.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_atlas_api.py -v`
Expected: FAIL (404s).

- [ ] **Step 3: Implement `app/api/atlas.py`**

```python
"""Read-only atlas endpoints for the UI (catalog + dashboard overview).

Every number goes through AtlasTools (audited, provenance-bearing). This router
only selects governed metrics and date windows; it never builds SQL.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.overview import (
    ALLOWED_DAYS,
    kpi_from_compare,
    kpi_from_query,
    pick_breakdown_metric,
    pick_kpi_metrics,
    windows,
)
from app.atlas import AtlasTools
from app.database import get_db
from app.middleware import AuthUser, get_current_user

router = APIRouter(prefix="/api/v1/atlas", tags=["atlas"])

BREAKDOWN_LIMIT = 5


def _tools(user: AuthUser, db: AsyncSession) -> AtlasTools:
    return AtlasTools(user_uid=user.uid, surface="api", db=db)


@router.get("/metrics")
async def metrics_catalog(
    user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return await _tools(user, db).execute("list_metrics", {})


@router.get("/overview")
async def overview(
    days: int = Query(30),
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if days not in ALLOWED_DAYS:
        raise HTTPException(status_code=422, detail=f"days must be one of {list(ALLOWED_DAYS)}")
    tools = _tools(user, db)
    metrics = tools.registry.metrics
    (start, end), (prev_start, prev_end) = windows(days, datetime.now(UTC).date())

    kpis: list[dict] = []
    for metric in pick_kpi_metrics(metrics):
        if metric.time_scope == "snapshot":
            result = await tools.execute("query_metric", {"metric_id": metric.id})
            kpi = kpi_from_query(metric, result)
        else:
            result = await tools.execute(
                "compare_periods",
                {
                    "metric_id": metric.id,
                    "period_a_start": start,
                    "period_a_end": end,
                    "period_b_start": prev_start,
                    "period_b_end": prev_end,
                },
            )
            kpi = kpi_from_compare(metric, result)
        if kpi is not None:
            kpis.append(kpi)

    breakdown = None
    if (bm := pick_breakdown_metric(metrics)) is not None:
        args = {"metric_id": bm.id, "limit": BREAKDOWN_LIMIT}
        if bm.time_scope == "range":
            args |= {"start_date": start, "end_date": end}
        result = await tools.execute("metric_breakdown", args)
        if "error" not in result and result.get("provenance"):
            breakdown = {
                "metric_id": bm.id,
                "name": result["name"],
                "unit": result["unit"],
                "rows": result["rows"],
                "provenance": result["provenance"][0],
            }

    return {"days": days, "start_date": start, "end_date": end, "kpis": kpis, "breakdown": breakdown}
```

`app/api/__init__.py`:
```python
from app.api.atlas import router as atlas_router
from app.api.chat import router as chat_router

__all__ = ["atlas_router", "chat_router"]
```

`app/main.py`: `from app.api import atlas_router, chat_router` and add `app.include_router(atlas_router)` after the chat router.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_atlas_api.py tests/test_overview.py -v`
Expected: PASS. If `revenue` value differs, check `tests/conftest.py` seed (1500/day) and the window (7 full days ending yesterday, seeded for 10 days back). Fix the code, not the assertion.

- [ ] **Step 5: Full backend gate**

Run: `uv run pytest --cov=app && uv run ruff check . && uv run ruff format --check .`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/api tests/test_atlas_api.py app/main.py
git commit -m "feat(api): audited metrics catalog and dashboard overview endpoints"
```

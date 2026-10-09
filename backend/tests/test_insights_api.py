from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.main import app as asgi_app
from app.models.audit import AtlasAuditLog
from tests.access_helpers import grant_all


@pytest_asyncio.fixture
async def api(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    await grant_all(db)
    transport = ASGITransport(app=asgi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_metrics_catalog_lists_governed_metrics(api: AsyncClient) -> None:
    body = (await api.get("/api/v1/atlas/metrics")).json()
    demo = next(s for s in body["sources"] if s["id"] == "demo")
    assert {"revenue", "orders_count"} <= {m["id"] for m in demo["metrics"]}
    revenue = next(m for m in demo["metrics"] if m["id"] == "revenue")
    expected = {
        "id",
        "name",
        "description",
        "unit",
        "time_scope",
        "has_breakdown",
        "entity",
    }
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
    await api.get("/api/v1/atlas/overview?days=7")
    rows = (await db.execute(select(AtlasAuditLog))).scalars().all()
    assert rows
    assert all(r.surface == "api" for r in rows)


async def test_without_grants_the_catalog_is_empty(db: AsyncSession) -> None:
    transport = ASGITransport(app=asgi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        catalog = (await client.get("/api/v1/atlas/metrics")).json()
        overview = (await client.get("/api/v1/atlas/overview?days=7")).json()
    assert catalog == {"sources": []}
    assert overview["kpis"] == []
    denials = (
        (
            await db.execute(
                select(AtlasAuditLog).where(AtlasAuditLog.decision == "deny")
            )
        )
        .scalars()
        .all()
    )
    assert denials == []

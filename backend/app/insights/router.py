"""Thin HTTP edge for insights: parse → service → schema.

Two routers share the `/api/v1/atlas` prefix: the dashboard needs `chat:use`;
the catalog picker is gated by the admin capabilities instead (P5-D17).
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.access import (
    ADMIN_GROUPS,
    ADMIN_USERS,
    CHAT_USE,
    AccessAdmin,
    Actor,
    get_access_admin,
    get_actor,
    require_capability,
)
from app.atlas import AtlasRegistry
from app.insights.catalog_resources import build_catalog_resources
from app.insights.dependencies import get_catalog_registry, get_insights_service
from app.insights.schemas import CatalogResourcesOut, MetricsCatalog, Overview
from app.insights.selection import ALLOWED_DAYS
from app.insights.service import InsightsService

_dashboard = APIRouter(
    prefix="/api/v1/atlas",
    tags=["insights"],
    dependencies=[Depends(require_capability(CHAT_USE))],
)
_catalog_admin = APIRouter(prefix="/api/v1/atlas", tags=["insights"])


@_dashboard.get("/metrics", response_model=MetricsCatalog)
async def metrics_catalog(
    service: InsightsService = Depends(get_insights_service),
) -> MetricsCatalog:
    return await service.catalog()


@_dashboard.get("/overview", response_model=Overview)
async def overview(
    days: int = Query(30),
    service: InsightsService = Depends(get_insights_service),
) -> Overview:
    if days not in ALLOWED_DAYS:
        raise HTTPException(
            status_code=422, detail=f"days must be one of {list(ALLOWED_DAYS)}"
        )
    return await service.overview(days, datetime.now(UTC).date())


@_catalog_admin.get("/catalog/resources", response_model=CatalogResourcesOut)
async def catalog_resources(
    as_user: UUID | None = None,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
    registry: AtlasRegistry = Depends(get_catalog_registry),
) -> CatalogResourcesOut:
    """Catalog metadata for the grant picker; with `as_user`, that user's
    decision on every path (admin:users, same tenant, else 403/404)."""
    if as_user is None:
        actor.require_any(ADMIN_USERS, ADMIN_GROUPS)
        return build_catalog_resources(registry, None)
    policy = await admin.effective_access(actor, as_user)
    return build_catalog_resources(registry, policy)


router = APIRouter()
router.include_router(_dashboard)
router.include_router(_catalog_admin)

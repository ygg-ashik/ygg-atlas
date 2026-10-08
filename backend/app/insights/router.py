"""Thin HTTP edge for insights: parse → service → schema."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.insights.dependencies import get_insights_service
from app.insights.schemas import MetricsCatalog, Overview
from app.insights.selection import ALLOWED_DAYS
from app.insights.service import InsightsService

router = APIRouter(prefix="/api/v1/atlas", tags=["insights"])


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
        raise HTTPException(
            status_code=422, detail=f"days must be one of {list(ALLOWED_DAYS)}"
        )
    return await service.overview(days, datetime.now(UTC).date())

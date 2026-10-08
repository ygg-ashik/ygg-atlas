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

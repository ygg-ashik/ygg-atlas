"""Response shapes for the insights endpoints (contract §2)."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ProvenanceScopeOut(BaseModel):
    restricted: bool
    dimensions: list[str]


class ProvenanceMaskingOut(BaseModel):
    label_class: str
    mode: str


class ProvenanceOut(BaseModel):
    tool: str
    source: str
    metric_id: str | None = None
    metric_name: str | None = None
    freshness: str | None = None
    executed_at: str
    scope: ProvenanceScopeOut | None = None
    masking: ProvenanceMaskingOut | None = None


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


# Catalog metadata for the grant picker and the per-user preview (phase 5).
# Metadata only: no numeric field anywhere, no data, no scope dimensions.


class ResourceDecisionOut(BaseModel):
    allowed: bool
    reason: str
    origin: str | None  # "user" or "group:<name>"; None when no grant decided it


class CatalogItemOut(BaseModel):
    path: str
    id: str
    name: str
    kind: Literal["metric", "funnel"]
    decision: ResourceDecisionOut | None = None


class CatalogEntityOut(BaseModel):
    path: str
    name: str
    items: list[CatalogItemOut]
    decision: ResourceDecisionOut | None = None


class CatalogSourceOut(BaseModel):
    id: str
    name: str
    entities: list[CatalogEntityOut]


class CatalogResourcesOut(BaseModel):
    sources: list[CatalogSourceOut]
    as_user: UUID | None = None

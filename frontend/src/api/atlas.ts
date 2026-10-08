// src/api/atlas.ts
// Governed metrics catalog client (GET /api/v1/atlas/metrics, served by app/insights).
import { api } from './axios-instance';

export interface CatalogMetric {
  id: string;
  name: string;
  description: string;
  unit: string;
  time_scope: 'range' | 'snapshot';
  has_breakdown: boolean;
  entity: string;
}
export interface CatalogFunnel {
  id: string;
  name: string;
  description: string;
  entity: string;
}
export interface CatalogSource {
  id: string;
  name: string;
  description: string;
  metrics: CatalogMetric[];
  funnels: CatalogFunnel[];
}
export interface MetricsCatalog {
  sources: CatalogSource[];
}

export async function fetchMetricsCatalog(): Promise<MetricsCatalog> {
  const { data } = await api.get<MetricsCatalog>('/atlas/metrics');
  return data;
}

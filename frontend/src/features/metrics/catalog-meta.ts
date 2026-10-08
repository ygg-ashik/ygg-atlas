// src/features/metrics/catalog-meta.ts
import type { CatalogMetric } from '@/api/atlas';

/** Secondary line under a metric's definition: time scope, unit, breakdown. */
export function metricMeta(
  m: Pick<CatalogMetric, 'time_scope' | 'unit' | 'has_breakdown'>,
): string {
  const parts = [m.time_scope === 'snapshot' ? 'Snapshot (as of now)' : 'Range (needs dates)'];
  if (m.unit) parts.push(m.unit);
  if (m.has_breakdown) parts.push('has breakdown');
  return parts.join(' · ');
}

export const FUNNEL_META = 'Funnel · step conversion and biggest drop-off';

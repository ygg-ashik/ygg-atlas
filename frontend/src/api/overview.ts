// GET /api/v1/atlas/overview — shared contract with backend app/insights (plan 00 §2).
import { api } from './axios-instance';
import type { Provenance } from './chat';

export type OverviewDays = 7 | 30 | 90;

export interface OverviewKpi {
  metric_id: string;
  name: string;
  unit: string;
  value: number;
  previous: number | null;
  delta_pct: number | null;
  good_direction: 'up' | 'down';
  provenance: Provenance;
}

export interface OverviewBreakdown {
  metric_id: string;
  name: string;
  unit: string;
  rows: { label: string; value: number }[];
  provenance: Provenance;
  /** Rows hidden by `suppress` masking; set only when labels were suppressed. */
  suppressed_rows?: number | null;
  /** What the bucket `Others` row sums; set only for `bucket` masking. */
  others_covers?: string | null;
}

export interface Overview {
  days: number;
  start_date: string;
  end_date: string;
  kpis: OverviewKpi[];
  breakdown: OverviewBreakdown | null;
}

export async function fetchOverview(days: OverviewDays): Promise<Overview> {
  const { data } = await api.get<Overview>('/atlas/overview', { params: { days } });
  return data;
}

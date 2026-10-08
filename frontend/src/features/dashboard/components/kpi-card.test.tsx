import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { KpiCard } from './kpi-card';

const kpi = {
  metric_id: 'aov',
  name: 'Avg order value',
  unit: 'AED',
  value: 126.1,
  previous: 129.1,
  delta_pct: -2.3,
  good_direction: 'up' as const,
  provenance: {
    tool: 'compare_periods',
    source: 'demo',
    metric_id: 'aov',
    executed_at: '2026-10-08T00:00:00Z',
    freshness: '2020-01-01T00:00:00Z',
  },
};

describe('KpiCard', () => {
  it('shows name, accessible value, toned delta and an amber stale source chip', () => {
    render(<KpiCard kpi={kpi} />);
    expect(screen.getByText('Avg order value')).toBeInTheDocument();
    expect(screen.getByLabelText(/AED\s?126\.1/)).toBeInTheDocument();
    const delta = screen.getByText('▼ 2.3%');
    expect(delta).toHaveAttribute('data-tone', 'negative');
    expect(screen.getByText(/demo/).closest('[data-stale]')).toHaveAttribute('data-stale', 'true');
  });
});

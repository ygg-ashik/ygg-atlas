import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BreakdownCard } from './breakdown-card';

const breakdown = {
  metric_id: 'revenue',
  name: 'Revenue',
  unit: 'AED',
  rows: [
    { label: 'b2b', value: 1000 },
    { label: 'b2c', value: 500 },
  ],
  provenance: {
    tool: 'breakdown',
    source: 'emapi',
    metric_id: 'revenue',
    executed_at: '2026-10-08T00:00:00Z',
    freshness: '2020-01-01T00:00:00Z',
  },
};

describe('BreakdownCard', () => {
  it('lists rows with formatted values and bars scaled to the top row', () => {
    const { container } = render(<BreakdownCard breakdown={breakdown} />);
    expect(screen.getByRole('heading', { name: 'Top revenue' })).toBeInTheDocument();
    expect(screen.getByText(/AED\s?1K/)).toBeInTheDocument();
    const bars = container.querySelectorAll<HTMLElement>('[data-bar]');
    expect(bars[0]?.style.width).toBe('100%');
    expect(bars[1]?.style.width).toBe('50%');
  });

  it('carries a provenance chip so every number has a source (guardrail 2)', () => {
    render(<BreakdownCard breakdown={breakdown} />);
    expect(screen.getByText(/emapi/).closest('[data-stale]')).toHaveAttribute('data-stale', 'true');
  });
});

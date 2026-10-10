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

  it('shows scope and masking chips beside the source chip', () => {
    render(
      <BreakdownCard
        breakdown={{
          ...breakdown,
          provenance: {
            ...breakdown.provenance,
            scope: { restricted: true, dimensions: ['csm'] },
            masking: { label_class: 'business_name', mode: 'pseudonymise' },
          },
        }}
      />,
    );
    expect(screen.getByText('rows · scoped to csm')).toBeInTheDocument();
    expect(screen.getByText('account names · pseudonymised')).toBeInTheDocument();
  });

  it('says how many rows a suppressed breakdown hid instead of an empty table', () => {
    render(
      <BreakdownCard
        breakdown={{
          ...breakdown,
          rows: [],
          suppressed_rows: 4,
          provenance: {
            ...breakdown.provenance,
            masking: { label_class: 'business_name', mode: 'suppress' },
          },
        }}
      />,
    );
    expect(screen.getByText('4 rows hidden by name masking')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('uses the singular for one hidden row', () => {
    render(<BreakdownCard breakdown={{ ...breakdown, rows: [], suppressed_rows: 1 }} />);
    expect(screen.getByText('1 row hidden by name masking')).toBeInTheDocument();
  });

  it('states what the bucketed Others row covers', () => {
    render(
      <BreakdownCard
        breakdown={{
          ...breakdown,
          rows: [
            { label: 'Top 1', value: 1000 },
            { label: 'Others', value: 500 },
          ],
          others_covers: 'remaining fetched rows',
        }}
      />,
    );
    expect(screen.getByText('Others = remaining fetched rows')).toBeInTheDocument();
  });

  it('adds no masking note to an unmasked breakdown', () => {
    render(<BreakdownCard breakdown={breakdown} />);
    expect(screen.queryByText(/hidden by name masking|Others =/)).not.toBeInTheDocument();
  });

  it('says so when an unmasked breakdown has no rows', () => {
    render(<BreakdownCard breakdown={{ ...breakdown, rows: [] }} />);
    expect(screen.getByText('No data for this range')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('does not claim no data when rows were suppressed', () => {
    render(<BreakdownCard breakdown={{ ...breakdown, rows: [], suppressed_rows: 2 }} />);
    expect(screen.queryByText('No data for this range')).not.toBeInTheDocument();
  });
});

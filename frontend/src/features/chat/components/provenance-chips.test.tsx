import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Provenance } from '@/api/chat';
import { ProvenanceChips } from './provenance-chips';

const base: Provenance = {
  tool: 'query_metric',
  metric_id: 'revenue_total',
  metric_name: 'Total revenue',
  source: 'orders_db',
  freshness: '2h ago',
  executed_at: '2026-09-23T10:00:00Z',
};

describe('ProvenanceChips', () => {
  it('renders metric name, source, and freshness', () => {
    render(<ProvenanceChips provenance={[base]} />);
    expect(screen.getByText('Total revenue')).toBeInTheDocument();
    expect(screen.getByText('orders_db')).toBeInTheDocument();
    expect(screen.getByText('2h ago')).toBeInTheDocument();
  });

  it('falls back to the tool name when metric_name is absent', () => {
    render(
      <ProvenanceChips
        provenance={[
          { tool: 'list_metrics', source: 'atlas_registry', executed_at: base.executed_at },
        ]}
      />,
    );
    expect(screen.getByText('list_metrics')).toBeInTheDocument();
    expect(screen.getByText('atlas_registry')).toBeInTheDocument();
  });

  it('dedupes repeated executions of the same metric and source', () => {
    render(
      <ProvenanceChips provenance={[base, { ...base, executed_at: '2026-09-23T10:05:00Z' }]} />,
    );
    expect(screen.getAllByText('Total revenue')).toHaveLength(1);
  });

  it('keeps distinct chips for different sources', () => {
    render(
      <ProvenanceChips
        provenance={[
          base,
          { ...base, metric_id: 'orders_count', metric_name: 'Orders', source: 'ads_db' },
        ]}
      />,
    );
    expect(screen.getByText('Total revenue')).toBeInTheDocument();
    expect(screen.getByText('Orders')).toBeInTheDocument();
  });

  it('renders nothing for an empty list', () => {
    const { container } = render(<ProvenanceChips provenance={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

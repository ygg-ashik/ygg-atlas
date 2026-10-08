// src/features/metrics/metrics-page.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { MetricsPage } from './metrics-page';

vi.mock('@/api/hooks/use-atlas', () => ({
  useMetricsCatalog: () => ({
    isLoading: false,
    data: {
      sources: [
        {
          id: 'demo',
          name: 'Commerce (EMAPI)',
          description: '',
          metrics: [
            {
              id: 'revenue',
              name: 'Revenue',
              description: 'Sum of paid orders, excluding refunds.',
              unit: 'AED',
              time_scope: 'range',
              has_breakdown: true,
              entity: 'order',
            },
          ],
          funnels: [
            {
              id: 'checkout_funnel',
              name: 'Checkout funnel',
              description: 'View → purchase.',
              entity: 'checkout',
            },
          ],
        },
      ],
    },
  }),
}));

describe('MetricsPage', () => {
  it('groups governed metrics by source with mono ids', () => {
    render(
      <MemoryRouter>
        <MetricsPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { name: 'Commerce (EMAPI)' })).toHaveClass('font-serif');
    expect(screen.getByText('revenue')).toHaveClass('font-mono');
    expect(screen.getByText('Checkout funnel')).toBeInTheDocument();
  });

  it('expands a row to show the definition and an ask link', async () => {
    render(
      <MemoryRouter>
        <MetricsPage />
      </MemoryRouter>,
    );
    const row = screen.getByRole('button', { name: /Revenue/ });
    expect(row).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(row);
    expect(row).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Sum of paid orders, excluding refunds.')).toBeVisible();
    expect(screen.getByRole('link', { name: /Ask about this/ })).toHaveAttribute(
      'href',
      expect.stringContaining('/ask?q='),
    );
  });

  it('opens the row named in the URL hash', () => {
    render(
      <MemoryRouter initialEntries={['/metrics#metric-revenue']}>
        <MetricsPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole('button', { name: /Revenue/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });
});

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { OverviewPage } from './overview-page';

vi.mock('@number-flow/react', () => ({ default: () => null }));
const useOverview = vi.hoisted(() => vi.fn());
vi.mock('@/api/hooks/use-overview', () => ({ useOverview }));

const prov = { tool: 'compare_periods', source: 'demo', executed_at: 't' };
const loaded = {
  isLoading: false,
  isError: false,
  data: {
    days: 30,
    start_date: '2026-09-08',
    end_date: '2026-10-07',
    kpis: [
      {
        metric_id: 'revenue',
        name: 'Revenue',
        unit: 'AED',
        value: 4820000,
        previous: 4290000,
        delta_pct: 12.4,
        good_direction: 'up',
        provenance: prov,
      },
    ],
    breakdown: {
      metric_id: 'revenue',
      name: 'Revenue',
      unit: 'AED',
      rows: [
        { label: 'b2b', value: 1000 },
        { label: 'b2c', value: 500 },
      ],
      provenance: prov,
    },
  },
};
useOverview.mockReturnValue(loaded);

let path = '';
function Where() {
  const l = useLocation();
  path = l.pathname + l.search;
  return null;
}

describe('OverviewPage', () => {
  afterEach(() => {
    useOverview.mockReturnValue(loaded);
  });

  it('greets, shows KPIs, breakdown and presets that start a chat', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route
            path="*"
            element={
              <>
                <OverviewPage userName="Ashik Babu" />
                <Where />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(
      /Good (morning|afternoon|evening), Ashik/,
    );
    expect(screen.getByText('Revenue', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByText('b2b')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Campaign ROAS/ }));
    expect(path).toMatch(/^\/ask\?q=/);
  });

  it('switches range via the segmented control', async () => {
    render(
      <MemoryRouter>
        <OverviewPage userName="A" />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole('radio', { name: '7D' }));
    expect(useOverview).toHaveBeenLastCalledWith(7);
  });

  it('shows skeleton cards while the first load is in flight', () => {
    useOverview.mockReturnValue({ isLoading: true, isError: false, data: undefined });
    const { container } = render(
      <MemoryRouter>
        <OverviewPage userName="" />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(/, there$/);
    expect(screen.getByText(/Loading the latest numbers/)).toBeInTheDocument();
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(4);
  });

  it('states the failure and the next step when the overview cannot load', () => {
    useOverview.mockReturnValue({ isLoading: false, isError: true, data: undefined });
    render(
      <MemoryRouter>
        <OverviewPage userName="A" />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Couldn't load the latest numbers/)).toBeInTheDocument();
  });

  it('falls back to 30 days for an unknown ?days= value', () => {
    render(
      <MemoryRouter initialEntries={['/?days=365']}>
        <OverviewPage userName="A" />
      </MemoryRouter>,
    );
    expect(useOverview).toHaveBeenLastCalledWith(30);
    expect(screen.getByRole('radio', { name: '30D' })).toHaveAttribute('aria-checked', 'true');
  });
});

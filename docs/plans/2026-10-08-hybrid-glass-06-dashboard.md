# Hybrid Glass Track E-fe: Overview Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/` an Overview dashboard in Hybrid Glass:
- serif greeting
- a sliding range switch (7D/30D/90D)
- KPI cards with per-digit roll (NumberFlow), direction-aware deltas and source/freshness chips
- a top-N breakdown with growing bars
- a Higgsfield-style preset gallery that starts analyses in chat

**Architecture:** The new feature is `features/dashboard`. Data comes from `GET /api/v1/atlas/overview?days=` (contract §2, backend Track E-be), through `api/overview.ts` + `api/hooks/use-overview.ts`. Formatting and tone rules are pure functions (`format.ts`) with unit tests. Presets navigate to `/ask?q=…` (Track B Task 10). Data sits on solid cards, never on glass (DESIGN.md). The AI briefing card is deferred (needs LLM evals).

**Tech Stack:** React 19, `@number-flow/react`, `motion/react`, TanStack Query, react-router.

**Depends on:** Track A merged; E-be contract. **Branch/worktree:** `feature/hybrid-glass-e-fe` · from `frontend/`.

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `src/api/overview.ts`, `src/api/hooks/use-overview.ts` | Create | Contract types, fetcher, query hook |
| `src/features/dashboard/format.ts` (+ test) | Create | Number format per unit, delta tone, delta label |
| `src/features/dashboard/range-switch.tsx` (+ test) | Create | Segmented control with sliding thumb |
| `src/features/dashboard/kpi-card.tsx` (+ test) | Create | KPI card: label, delta, NumberFlow value, source chip |
| `src/features/dashboard/breakdown-card.tsx` | Create | Top-N table with growing bars |
| `src/features/dashboard/overview-page.tsx` (+ test) | Create | Page composition |
| `src/features/dashboard/index.ts` | Create | Public interface |
| `src/App.tsx` | Modify | `/` → Overview, nav entry |

---

### Task 1: Overview API client

**Files:** Create `src/api/overview.ts`, `src/api/hooks/use-overview.ts`

- [ ] **Step 1: Implement**

```ts
// src/api/overview.ts
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
```

```ts
// src/api/hooks/use-overview.ts
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { fetchOverview, type OverviewDays } from '../overview';

/** keepPreviousData: switching range morphs values instead of flashing a skeleton. */
export function useOverview(days: OverviewDays) {
  return useQuery({
    queryKey: ['atlas-overview', days],
    queryFn: () => fetchOverview(days),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}
```

- [ ] **Step 2: Typecheck + commit**

```bash
corepack pnpm typecheck
git add src/api/overview.ts src/api/hooks/use-overview.ts
git commit -m "feat(api): overview client"
```

---

### Task 2: Formatting + delta tone

**Files:** Create `src/features/dashboard/format.ts`, `src/features/dashboard/format.test.ts`

- [ ] **Step 1: Failing test**

```ts
// src/features/dashboard/format.test.ts
import { describe, expect, it } from 'vitest';
import { deltaLabel, deltaTone, formatKpi, numberFormat } from './format';

describe('dashboard format', () => {
  it('formats AED compactly as currency', () => {
    expect(formatKpi(4_820_000, 'AED')).toMatch(/AED\s?4\.82M/);
  });
  it('formats counts with grouping, compact above 100k', () => {
    expect(formatKpi(38214, 'orders')).toBe('38,214');
    expect(formatKpi(1_250_000, '')).toBe('1.3M');
  });
  it('keeps percent units', () => {
    expect(formatKpi(12.345, '%')).toBe('12.3%');
  });
  it('numberFormat is the Intl options NumberFlow receives', () => {
    expect(numberFormat('AED', 5)).toMatchObject({ style: 'currency', currency: 'AED' });
  });
  it('tone respects the metric direction', () => {
    expect(deltaTone(5, 'up')).toBe('positive');
    expect(deltaTone(5, 'down')).toBe('negative');
    expect(deltaTone(-2, 'down')).toBe('positive');
    expect(deltaTone(0, 'up')).toBe('neutral');
    expect(deltaTone(null, 'up')).toBe('neutral');
  });
  it('labels deltas with an arrow (color is never the only signal)', () => {
    expect(deltaLabel(12.4)).toBe('▲ 12.4%');
    expect(deltaLabel(-2.3)).toBe('▼ 2.3%');
    expect(deltaLabel(null)).toBe('');
  });
});
```

- [ ] **Step 2: Run → FAIL**

Run: `corepack pnpm vitest run src/features/dashboard/format.test.ts`

- [ ] **Step 3: Implement**

```ts
// src/features/dashboard/format.ts
export function numberFormat(unit: string, value: number): Intl.NumberFormatOptions {
  if (unit === 'AED') return { style: 'currency', currency: 'AED', notation: 'compact', maximumFractionDigits: 2 };
  if (unit === '%') return { maximumFractionDigits: 1 };
  return Math.abs(value) >= 100_000 ? { notation: 'compact', maximumFractionDigits: 1 } : { maximumFractionDigits: 1 };
}

export function formatKpi(value: number, unit: string): string {
  const text = new Intl.NumberFormat('en-US', numberFormat(unit, value)).format(value);
  return unit === '%' ? `${text}%` : text;
}

export type Tone = 'positive' | 'negative' | 'neutral';

export function deltaTone(deltaPct: number | null, good: 'up' | 'down'): Tone {
  if (deltaPct === null || deltaPct === 0) return 'neutral';
  const rising = deltaPct > 0;
  return rising === (good === 'up') ? 'positive' : 'negative';
}

export function deltaLabel(deltaPct: number | null): string {
  if (deltaPct === null) return '';
  return `${deltaPct >= 0 ? '▲' : '▼'} ${Math.abs(deltaPct).toFixed(1)}%`;
}
```

- [ ] **Step 4: Run → PASS, commit**

```bash
git add src/features/dashboard/format.ts src/features/dashboard/format.test.ts
git commit -m "feat(dashboard): KPI formatting and direction-aware deltas"
```

---

### Task 3: Range switch + KPI card

**Files:** Create `range-switch.tsx`, `range-switch.test.tsx`, `kpi-card.tsx`, `kpi-card.test.tsx` in `src/features/dashboard/`

- [ ] **Step 1: Failing tests**

```tsx
// src/features/dashboard/range-switch.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { RangeSwitch } from './range-switch';

describe('RangeSwitch', () => {
  it('is a radiogroup with the active range checked', async () => {
    const onChange = vi.fn();
    render(<RangeSwitch value={30} onChange={onChange} />);
    expect(screen.getByRole('radio', { name: '30D' })).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(screen.getByRole('radio', { name: '7D' }));
    expect(onChange).toHaveBeenCalledWith(7);
  });
});
```

```tsx
// src/features/dashboard/kpi-card.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { KpiCard } from './kpi-card';

const kpi = {
  metric_id: 'aov', name: 'Avg order value', unit: 'AED', value: 126.1, previous: 129.1, delta_pct: -2.3,
  good_direction: 'up' as const,
  provenance: { tool: 'compare_periods', source: 'demo', metric_id: 'aov', executed_at: '2026-10-08T00:00:00Z', freshness: '2020-01-01T00:00:00Z' },
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
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement**

```tsx
// src/features/dashboard/range-switch.tsx
import { motion } from 'motion/react';
import { cn, springDefault } from '@/ui';
import type { OverviewDays } from '@/api/overview';

const OPTIONS: OverviewDays[] = [7, 30, 90];

/** Apple segmented control: the thumb slides between options (shared layoutId). */
export function RangeSwitch({ value, onChange }: { value: OverviewDays; onChange: (d: OverviewDays) => void }) {
  return (
    <div role="radiogroup" aria-label="Date range" className="relative flex rounded-full bg-foreground/[0.05] p-[3px]">
      {OPTIONS.map((d) => {
        const active = d === value;
        return (
          <button
            key={d}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(d)}
            className={cn('relative z-[1] rounded-full px-3 py-1.5 text-label transition-colors', active ? 'text-ink' : 'text-muted-foreground')}
          >
            {active && (
              <motion.span
                layoutId="range-thumb"
                transition={springDefault}
                className="absolute inset-0 -z-[1] rounded-full bg-card shadow-[0_1px_3px_rgba(0,0,0,0.12),0_0_0_0.5px_hsl(var(--border))]"
              />
            )}
            {d}D
          </button>
        );
      })}
    </div>
  );
}
```

```tsx
// src/features/dashboard/kpi-card.tsx
import NumberFlow from '@number-flow/react';
import { cn } from '@/ui';
import { freshnessLabel, isStale } from '@/lib/freshness';
import type { OverviewKpi } from '@/api/overview';
import { deltaLabel, deltaTone, formatKpi, numberFormat } from './format';

const TONE = {
  positive: 'bg-positive/[0.12] text-positive',
  negative: 'bg-negative/[0.12] text-negative',
  neutral: 'bg-foreground/5 text-muted-foreground',
} as const;

/** DESIGN.md › kpi-card: solid card, digit roll, toned delta, provenance chip. */
export function KpiCard({ kpi }: { kpi: OverviewKpi }) {
  const tone = deltaTone(kpi.delta_pct, kpi.good_direction);
  const stale = isStale(kpi.provenance.freshness);
  return (
    <div className="rounded-card bg-card px-4 py-3.5 shadow-[0_0_0_1px_hsl(var(--border)/0.6),0_1px_2px_rgba(0,0,0,0.04)]">
      <div className="flex items-center justify-between gap-2 text-label text-muted-foreground">
        <span className="truncate">{kpi.name}</span>
        {kpi.delta_pct !== null && (
          <span data-tone={tone} className={cn('shrink-0 rounded-full px-[7px] py-0.5 text-caption font-semibold', TONE[tone])}>
            {deltaLabel(kpi.delta_pct)}
          </span>
        )}
      </div>
      <div aria-label={formatKpi(kpi.value, kpi.unit)} className="tabular my-2 font-semibold text-metric-lg text-ink">
        <NumberFlow value={kpi.value} format={numberFormat(kpi.unit, kpi.value)} locales="en-US" suffix={kpi.unit === '%' ? '%' : undefined} aria-hidden />
      </div>
      <span
        data-stale={stale}
        className={cn(
          'inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-card-2 px-2.5 py-[3px] text-caption text-muted-foreground',
          stale && 'border-warning/40 text-warning',
        )}
      >
        <span className={cn('h-1.5 w-1.5 rounded-full', stale ? 'bg-warning' : 'bg-positive')} />
        {kpi.provenance.source}
        {kpi.provenance.freshness && ` · ${freshnessLabel(kpi.provenance.freshness)}`}
      </span>
    </div>
  );
}
```

- [ ] **Step 4: Run → PASS** (if NumberFlow's custom element fails in happy-dom, mock it in the test with `vi.mock('@number-flow/react', () => ({ default: () => null }))`. The accessible value comes from the wrapper's `aria-label`.)

- [ ] **Step 5: Commit**

```bash
git add src/features/dashboard
git commit -m "feat(dashboard): range switch and KPI cards with digit roll"
```

---

### Task 4: Breakdown card + Overview page

**Files:** Create `breakdown-card.tsx`, `overview-page.tsx`, `overview-page.test.tsx`, `index.ts` in `src/features/dashboard/`

- [ ] **Step 1: Failing page test**

```tsx
// src/features/dashboard/overview-page.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { OverviewPage } from './overview-page';

vi.mock('@number-flow/react', () => ({ default: () => null }));
const useOverview = vi.hoisted(() => vi.fn());
vi.mock('@/api/hooks/use-overview', () => ({ useOverview }));

const prov = { tool: 'compare_periods', source: 'demo', executed_at: 't' };
useOverview.mockReturnValue({
  isLoading: false,
  data: {
    days: 30, start_date: '2026-09-08', end_date: '2026-10-07',
    kpis: [{ metric_id: 'revenue', name: 'Revenue', unit: 'AED', value: 4820000, previous: 4290000, delta_pct: 12.4, good_direction: 'up', provenance: prov }],
    breakdown: { metric_id: 'revenue', name: 'Revenue', unit: 'AED', rows: [{ label: 'b2b', value: 1000 }, { label: 'b2c', value: 500 }], provenance: prov },
  },
});

let path = '';
function Where() {
  const l = useLocation();
  path = l.pathname + l.search;
  return null;
}

describe('OverviewPage', () => {
  it('greets, shows KPIs, breakdown and presets that start a chat', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes><Route path="*" element={<><OverviewPage userName="Ashik Babu" /><Where /></>} /></Routes>
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(/Good (morning|afternoon|evening), Ashik/);
    expect(screen.getByText('Revenue', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByText('b2b')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Campaign ROAS/ }));
    expect(path).toMatch(/^\/ask\?q=/);
  });

  it('switches range via the segmented control', async () => {
    render(<MemoryRouter><OverviewPage userName="A" /></MemoryRouter>);
    await userEvent.click(screen.getByRole('radio', { name: '7D' }));
    expect(useOverview).toHaveBeenLastCalledWith(7);
  });
});
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement**

```tsx
// src/features/dashboard/breakdown-card.tsx
import type { OverviewBreakdown } from '@/api/overview';
import { formatKpi } from './format';

/** Top-N table: tabular figures, accent bars grow in staggered by 60ms. */
export function BreakdownCard({ breakdown }: { breakdown: OverviewBreakdown }) {
  const max = Math.max(...breakdown.rows.map((r) => r.value), 1);
  return (
    <div className="rounded-card bg-card px-[18px] py-4 shadow-[0_0_0_1px_hsl(var(--border)/0.6),0_1px_2px_rgba(0,0,0,0.04)]">
      <h3 className="mb-2.5 font-serif text-section text-ink">Top {breakdown.name.toLowerCase()}</h3>
      <table className="tabular w-full text-[13.5px]">
        <tbody>
          {breakdown.rows.map((r, i) => (
            <tr key={r.label} className="border-b border-border/50 last:border-0">
              <td className="py-2 pr-2 text-body">{r.label}</td>
              <td className="py-2 pr-3 text-right text-ink">{formatKpi(r.value, breakdown.unit)}</td>
              <td className="w-[36%] py-2">
                <div className="h-1.5 overflow-hidden rounded-full bg-primary/15">
                  <div
                    className="h-full origin-left animate-[grow_900ms_cubic-bezier(.22,1,.36,1)_both] rounded-full bg-primary"
                    style={{ width: `${(r.value / max) * 100}%`, animationDelay: `${100 + i * 60}ms` }}
                  />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

Add the `grow` keyframe to `tailwind.config.js` › `theme.extend.keyframes`: `grow: { from: { transform: 'scaleX(0)' }, to: { transform: 'scaleX(1)' } },`

```tsx
// src/features/dashboard/overview-page.tsx
import { useNavigate, useSearchParams } from 'react-router-dom';
import { PresetCard, Toolbar } from '@/ui';
import { useOverview } from '@/api/hooks/use-overview';
import type { OverviewDays } from '@/api/overview';
import { RangeSwitch } from './range-switch';
import { KpiCard } from './kpi-card';
import { BreakdownCard } from './breakdown-card';

const PRESETS = [
  { title: 'Revenue review', description: 'Trend, drivers, top accounts', preview: 'line' as const, question: 'What drove revenue over the last 30 days?' },
  { title: 'Campaign ROAS', description: 'By channel and creative', preview: 'bars' as const, question: 'What was ROAS by channel over the last 30 days?' },
  { title: 'Redemption funnel', description: 'Where gift cards drop off', preview: 'funnel' as const, question: 'Where do users drop off in checkout over the last 30 days?' },
  { title: 'Account health', description: 'Churn risk and CSM load', preview: 'line' as const, question: 'How many accounts are currently at risk?' },
];

function greeting(now = new Date()) {
  const h = now.getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

/** Overview dashboard (DESIGN.md › Dashboard). Data on solid cards, chrome on glass. */
export function OverviewPage({ userName }: { userName: string }) {
  const [params, setParams] = useSearchParams();
  const days = ([7, 30, 90].includes(Number(params.get('days'))) ? Number(params.get('days')) : 30) as OverviewDays;
  const { data, isLoading } = useOverview(days);
  const navigate = useNavigate();
  const first = userName.split(' ')[0] || 'there';

  return (
    <div className="relative h-full">
      <Toolbar title="Overview">
        <RangeSwitch value={days} onChange={(d) => setParams({ days: String(d) }, { replace: true })} />
      </Toolbar>
      <div className="absolute inset-0 overflow-y-auto">
        <div className="mx-auto max-w-[1080px] px-7 pb-20 pt-[84px]">
          <h2 className="mt-1.5 font-serif text-display text-ink">
            {greeting()}, {first}
          </h2>
          <p className="mb-5 mt-0.5 text-muted-foreground">
            {data ? `${data.start_date} → ${data.end_date} across all connected sources.` : 'Loading the latest numbers…'}
          </p>

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {isLoading && !data
              ? Array.from({ length: 4 }, (_, i) => <div key={i} className="h-[118px] animate-pulse rounded-card bg-card-2" />)
              : data?.kpis.map((k) => <KpiCard key={k.metric_id} kpi={k} />)}
          </div>

          {data?.breakdown && (
            <div className="mt-3 grid gap-3 lg:grid-cols-[1.6fr_1fr]">
              <BreakdownCard breakdown={data.breakdown} />
            </div>
          )}

          <h3 className="mb-1 mt-7 font-serif text-[20px] text-ink">Start an analysis</h3>
          <p className="mb-3 text-label text-muted-foreground">Presets for common questions. Hover a card to preview what you&apos;ll get.</p>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {PRESETS.map((p) => (
              <PresetCard key={p.title} title={p.title} description={p.description} preview={p.preview} onSelect={() => navigate(`/ask?q=${encodeURIComponent(p.question)}`)} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
```

```ts
// src/features/dashboard/index.ts
// Public interface of the dashboard feature.
export { OverviewPage } from './overview-page';
```

- [ ] **Step 4: Run → PASS, commit**

```bash
corepack pnpm vitest run src/features/dashboard
git add src/features/dashboard tailwind.config.js
git commit -m "feat(dashboard): overview page with KPIs, breakdown and presets"
```

---

### Task 5: Make `/` the Overview

**Files:** Modify `src/App.tsx`

- [ ] **Step 1: Edit**

```tsx
import { LayoutDashboard } from 'lucide-react';
import { OverviewPage } from '@/features/dashboard';
```
Prepend to `NAV`: `{ to: '/', label: 'Overview', icon: LayoutDashboard },`. Note: `NavLink` to `/` must use `end` so it isn't active on every route. In `features/layout/shell.tsx` add `end={to === '/'}` to the `NavLink`.

Add a small route element inside `App.tsx` (it already has `useAuth`):
```tsx
function Home() {
  const { user } = useAuth();
  return <OverviewPage userName={user?.name ?? ''} />;
}
```
and replace `<Route index element={<Navigate to="/ask" replace />} />` with `<Route index element={<Home />} />`.

- [ ] **Step 2: Gate + visual check**

Run: `corepack pnpm test && corepack pnpm lint && corepack pnpm typecheck`
Expected: PASS.

Run the app against the backend with E-be merged. Compare with reference Mode ①, case 1:
- digits roll on load and on range change, with no skeleton flash thanks to `keepPreviousData`
- the thumb slides
- the delta tone respects good_direction
- stale sources show amber
- presets preview on hover and open chat with the question sent
- dark mode and reduced-motion (digits set instantly) are correct

- [ ] **Step 3: Commit**

```bash
git add src/App.tsx src/features/layout/shell.tsx
git commit -m "feat(app): Overview dashboard as home"
```

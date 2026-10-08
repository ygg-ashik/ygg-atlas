# Hybrid Glass Track D1: Metrics Catalog + ⌘K Palette Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Follow the `engineering-standards` skill before writing code and the `production-code-review` skill before calling the track done. Gate: `make check` from the repo root (run `make format` first: the code below predates prettier/ruff formatting).

**Goal:** Add a Metrics page (an Apple inset grouped list of every governed metric and funnel, rows that expand on a spring, mono ids, "Ask about this") and a Spotlight-style ⌘K command palette (pages, metrics, threads, "Ask …").

**Architecture:** There are two new self-contained features:
- `features/metrics`: the catalog page.
- `features/command`: the palette, its trigger and the hotkey.

Both read the catalog through a new `api/atlas.ts` + `api/hooks/use-atlas.ts` (contract §2, backend Track E-be). Starting a question navigates to `/ask?q=…` (Track B Task 10). `App.tsx` composes everything. Features never import each other.

**Tech Stack:** React 19, `cmdk`, `motion/react`, TanStack Query, react-router.

**Depends on:** Track A merged. The Track E-be endpoint contract (code against types and mocks; it works end-to-end once E-be merges). **Branch/worktree:** `feature/hybrid-glass-d1` · from `frontend/`.

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `src/api/atlas.ts` | Create | Catalog types (contract §2) + `fetchMetricsCatalog` |
| `src/api/hooks/use-atlas.ts` | Create | `useMetricsCatalog` |
| `src/features/metrics/metrics-page.tsx` (+ test) | Create | Inset grouped list, expandable rows, hash deep-link |
| `src/features/metrics/ask.ts` (+ test) | Create | Question template for "Ask about this" |
| `src/features/metrics/index.ts` | Create | Public interface |
| `src/features/command/command-palette.tsx` (+ test) | Create | cmdk dialog: pages, metrics, threads, Ask |
| `src/features/command/index.ts` | Create | Public interface |
| `src/App.tsx` | Modify | `/metrics` route, nav entry, palette + trigger |
| `vitest.setup.ts` | Modify (only if needed) | `scrollIntoView` polyfill for cmdk |

---

### Task 1: Catalog API client

**Files:** Create `src/api/atlas.ts`, `src/api/hooks/use-atlas.ts`

- [ ] **Step 1: Implement (types are the contract, verbatim)**

```ts
// src/api/atlas.ts
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
```

```ts
// src/api/hooks/use-atlas.ts
import { useQuery } from '@tanstack/react-query';
import { fetchMetricsCatalog } from '../atlas';

/** The governed catalog changes only on deploy, so cache it generously. */
export function useMetricsCatalog() {
  return useQuery({ queryKey: ['atlas-metrics'], queryFn: fetchMetricsCatalog, staleTime: 5 * 60_000 });
}
```

- [ ] **Step 2: Typecheck + commit**

Run: `corepack pnpm typecheck` → PASS

```bash
git add src/api/atlas.ts src/api/hooks/use-atlas.ts
git commit -m "feat(api): metrics catalog client"
```

---

### Task 2: "Ask about this" question template

**Files:** Create `src/features/metrics/ask.ts`, `src/features/metrics/ask.test.ts`

- [ ] **Step 1: Failing test**

```ts
// src/features/metrics/ask.test.ts
import { describe, expect, it } from 'vitest';
import { askHref } from './ask';

describe('askHref', () => {
  it('asks range metrics for the last 30 days', () => {
    expect(askHref({ name: 'Corporate revenue', time_scope: 'range' })).toBe(
      '/ask?q=What%20was%20Corporate%20revenue%20over%20the%20last%2030%20days%3F',
    );
  });
  it('asks snapshot metrics as of now', () => {
    expect(askHref({ name: 'Open tasks', time_scope: 'snapshot' })).toBe('/ask?q=What%20is%20Open%20tasks%20right%20now%3F');
  });
  it('asks funnels for drop-off', () => {
    expect(askHref({ name: 'Checkout funnel' })).toBe(
      '/ask?q=Where%20do%20users%20drop%20off%20in%20Checkout%20funnel%20over%20the%20last%2030%20days%3F',
    );
  });
});
```

- [ ] **Step 2: Run → FAIL (module not found)**

Run: `corepack pnpm vitest run src/features/metrics/ask.test.ts`

- [ ] **Step 3: Implement**

```ts
// src/features/metrics/ask.ts
// Entry point into chat: /ask?q=… (handled by the chat feature).
export function askHref(item: { name: string; time_scope?: 'range' | 'snapshot' }): string {
  return `/ask?q=${encodeURIComponent(question(item))}`;
}

function question(item: { name: string; time_scope?: 'range' | 'snapshot' }): string {
  if (item.time_scope === 'snapshot') return `What is ${item.name} right now?`;
  if (item.time_scope === 'range') return `What was ${item.name} over the last 30 days?`;
  return `Where do users drop off in ${item.name} over the last 30 days?`;
}
```

- [ ] **Step 4: Run → PASS, commit**

```bash
git add src/features/metrics/ask.ts src/features/metrics/ask.test.ts
git commit -m "feat(metrics): ask-about-this question template"
```

---

### Task 3: Metrics catalog page

**Files:** Create `src/features/metrics/metrics-page.tsx`, `src/features/metrics/metrics-page.test.tsx`, `src/features/metrics/index.ts`

- [ ] **Step 1: Failing test**

```tsx
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
            { id: 'revenue', name: 'Revenue', description: 'Sum of paid orders, excluding refunds.', unit: 'AED', time_scope: 'range', has_breakdown: true, entity: 'order' },
          ],
          funnels: [{ id: 'checkout_funnel', name: 'Checkout funnel', description: 'View → purchase.', entity: 'checkout' }],
        },
      ],
    },
  }),
}));

describe('MetricsPage', () => {
  it('groups governed metrics by source with mono ids', () => {
    render(<MemoryRouter><MetricsPage /></MemoryRouter>);
    expect(screen.getByRole('heading', { name: 'Commerce (EMAPI)' })).toHaveClass('font-serif');
    expect(screen.getByText('revenue')).toHaveClass('font-mono');
    expect(screen.getByText('Checkout funnel')).toBeInTheDocument();
  });

  it('expands a row to show the definition and an ask link', async () => {
    render(<MemoryRouter><MetricsPage /></MemoryRouter>);
    const row = screen.getByRole('button', { name: /Revenue/ });
    expect(row).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(row);
    expect(row).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Sum of paid orders, excluding refunds.')).toBeVisible();
    expect(screen.getByRole('link', { name: /Ask about this/ })).toHaveAttribute('href', expect.stringContaining('/ask?q='));
  });

  it('opens the row named in the URL hash', () => {
    render(<MemoryRouter initialEntries={['/metrics#metric-revenue']}><MetricsPage /></MemoryRouter>);
    expect(screen.getByRole('button', { name: /Revenue/ })).toHaveAttribute('aria-expanded', 'true');
  });
});
```

- [ ] **Step 2: Run → FAIL**

Run: `corepack pnpm vitest run src/features/metrics`

- [ ] **Step 3: Implement**

```tsx
// src/features/metrics/metrics-page.tsx
import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { ChevronRight } from 'lucide-react';
import { cn, springDefault, Toolbar, withReducedMotion } from '@/ui';
import { useMetricsCatalog } from '@/api/hooks/use-atlas';
import { askHref } from './ask';

interface RowProps {
  anchor: string;
  name: string;
  id: string;
  description: string;
  meta: string;
  ask: string;
  defaultOpen: boolean;
}

function Row({ anchor, name, id, description, meta, ask, defaultOpen }: RowProps) {
  const [open, setOpen] = useState(defaultOpen);
  const reduced = useReducedMotion();
  return (
    <li id={anchor} className="border-b border-border/60 last:border-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2.5 px-4 py-3 text-left transition-colors duration-200 hover:bg-foreground/[0.03]"
      >
        <span className="text-[14.5px] font-medium text-ink">{name}</span>
        <span className="font-mono text-[11px] text-muted-2">{id}</span>
        <ChevronRight className={cn('ml-auto h-4 w-4 text-muted-2 transition-transform duration-300 ease-out', open && 'rotate-90')} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={withReducedMotion(springDefault, reduced)}
            className="overflow-hidden"
          >
            <div className="space-y-2 px-4 pb-3.5 text-label text-body">
              <p>{description || 'No description yet.'}</p>
              <p className="text-caption text-muted-foreground">{meta}</p>
              <Link to={ask} className="inline-block text-label font-medium text-primary-text hover:underline">
                Ask about this →
              </Link>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}

/** Every governed metric Atlas can answer with (DESIGN.md › inset-list). */
export function MetricsPage() {
  const { data, isLoading } = useMetricsCatalog();
  const { hash } = useLocation();
  const target = hash.replace(/^#/, '');

  return (
    <div className="relative h-full">
      <Toolbar title="Metrics" />
      <div className="absolute inset-0 overflow-y-auto">
        <div className="mx-auto max-w-[760px] px-6 pb-16 pt-[84px]">
          <h2 className="font-serif text-display text-ink">Metrics</h2>
          <p className="mb-6 mt-1 text-muted-foreground">Every governed metric Atlas can answer with. Open one to see its definition.</p>
          {isLoading && <p className="text-label text-muted-foreground">Loading catalog…</p>}
          {data?.sources.map((source) => (
            <section key={source.id} className="mb-6" aria-labelledby={`src-${source.id}`}>
              <h3 id={`src-${source.id}`} className="px-1 pb-2 font-serif text-section text-ink">
                {source.name}
              </h3>
              <ul className="overflow-hidden rounded-lg bg-card shadow-[0_0_0_1px_hsl(var(--border)/0.6)]">
                {source.metrics.map((m) => (
                  <Row
                    key={m.id}
                    anchor={`metric-${m.id}`}
                    name={m.name}
                    id={m.id}
                    description={m.description}
                    meta={`${m.time_scope === 'snapshot' ? 'Snapshot (as of now)' : 'Range (needs dates)'}${m.unit ? ` · ${m.unit}` : ''}${m.has_breakdown ? ' · has breakdown' : ''}`}
                    ask={askHref(m)}
                    defaultOpen={target === `metric-${m.id}`}
                  />
                ))}
                {source.funnels.map((f) => (
                  <Row
                    key={f.id}
                    anchor={`metric-${f.id}`}
                    name={f.name}
                    id={f.id}
                    description={f.description}
                    meta="Funnel · step conversion and biggest drop-off"
                    ask={askHref(f)}
                    defaultOpen={target === `metric-${f.id}`}
                  />
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
```

```ts
// src/features/metrics/index.ts
// Public interface of the metrics feature.
export { MetricsPage } from './metrics-page';
```

- [ ] **Step 4: Run → PASS, commit**

Run: `corepack pnpm vitest run src/features/metrics` → PASS

```bash
git add src/features/metrics
git commit -m "feat(metrics): governed metrics catalog page"
```

---

### Task 4: ⌘K command palette

**Files:** Create `src/features/command/command-palette.tsx`, `src/features/command/command-palette.test.tsx`, `src/features/command/index.ts`

- [ ] **Step 1: Failing test**

```tsx
// src/features/command/command-palette.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { CommandPalette } from './command-palette';

vi.mock('@/api/hooks/use-atlas', () => ({
  useMetricsCatalog: () => ({
    data: { sources: [{ id: 'demo', name: 'Commerce', description: '', funnels: [],
      metrics: [{ id: 'revenue', name: 'Revenue', description: '', unit: 'AED', time_scope: 'range', has_breakdown: true, entity: 'order' }] }] },
  }),
}));
vi.mock('@/api/hooks/use-chat-sessions', () => ({
  useChatSessions: () => ({ data: [{ id: 's1', title: 'Q3 review', created_at: '', updated_at: '' }] }),
}));

let path = '';
function Where() {
  const l = useLocation();
  path = l.pathname + l.search + l.hash;
  return null;
}
const setup = () =>
  render(
    <MemoryRouter initialEntries={['/ask']}>
      <Routes><Route path="*" element={<><CommandPalette /><Where /></>} /></Routes>
    </MemoryRouter>,
  );

describe('CommandPalette', () => {
  it('opens with ⌘K and jumps to a metric', async () => {
    setup();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    const input = await screen.findByPlaceholderText(/Search metrics, threads/);
    await userEvent.type(input, 'reven');
    await userEvent.click(await screen.findByText('Revenue'));
    expect(path).toBe('/metrics#metric-revenue');
  });

  it('offers to ask the typed question', async () => {
    setup();
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const input = await screen.findByPlaceholderText(/Search metrics, threads/);
    await userEvent.type(input, 'why did aov drop');
    await userEvent.click(await screen.findByText(/Ask: “why did aov drop”/));
    expect(path).toBe('/ask?q=why%20did%20aov%20drop');
  });

  it('jumps to a thread', async () => {
    setup();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    await userEvent.click(await screen.findByText('Q3 review'));
    expect(path).toBe('/ask/s1');
  });
});
```

- [ ] **Step 2: Run → FAIL.** If cmdk throws `scrollIntoView is not a function`, add to `vitest.setup.ts`:
`Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || function () {};`

Run: `corepack pnpm vitest run src/features/command`

- [ ] **Step 3: Implement**

```tsx
// src/features/command/command-palette.tsx
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Command } from 'cmdk';
import { BarChart3, MessageCircle, Search, Sparkles } from 'lucide-react';
import { useMetricsCatalog } from '@/api/hooks/use-atlas';
import { useChatSessions } from '@/api/hooks/use-chat-sessions';

const PAGES = [
  { label: 'Overview', to: '/' },
  { label: 'Ask Atlas', to: '/ask' },
  { label: 'Metrics', to: '/metrics' },
];

const item =
  'flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-body data-[selected=true]:bg-primary/10 data-[selected=true]:text-ink';
const group = '[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-caption [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.06em] [&_[cmdk-group-heading]]:text-muted-2';

/** Spotlight-style palette (DESIGN.md › command-palette): glass, scrim, materialize. */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const navigate = useNavigate();
  const { data: catalog } = useMetricsCatalog();
  const { data: sessions = [] } = useChatSessions();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const go = (to: string) => {
    setOpen(false);
    setQuery('');
    navigate(to);
  };
  const metrics = catalog?.sources.flatMap((s) => [...s.metrics, ...s.funnels]) ?? [];

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command palette"
      overlayClassName="fixed inset-0 z-40 bg-black/20 data-[state=open]:animate-in data-[state=open]:fade-in-0"
      contentClassName="glass fixed left-1/2 top-[18%] z-50 w-[min(560px,calc(100vw-32px))] -translate-x-1/2 rounded-shell p-2.5 data-[state=open]:animate-materialize-in"
    >
      <div className="flex items-center gap-2 border-b border-border/70 px-2.5 pb-2.5">
        <Search className="h-4 w-4 text-muted-2" />
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder="Search metrics, threads, or ask a question…"
          className="w-full bg-transparent py-1.5 text-[17px] text-ink outline-none placeholder:text-muted-2"
        />
      </div>
      <Command.List className="max-h-[360px] overflow-y-auto pt-1.5">
        <Command.Empty className="px-2.5 py-6 text-center text-label text-muted-foreground">No matches.</Command.Empty>
        {query.trim() && (
          <Command.Group heading="Ask" className={group}>
            <Command.Item value={`ask ${query}`} onSelect={() => go(`/ask?q=${encodeURIComponent(query.trim())}`)} className={item}>
              <Sparkles className="h-4 w-4 text-primary-text" />
              Ask: “{query.trim()}”
              <kbd className="ml-auto font-mono text-caption text-muted-2">↵</kbd>
            </Command.Item>
          </Command.Group>
        )}
        <Command.Group heading="Metrics" className={group}>
          {metrics.map((m) => (
            <Command.Item key={m.id} value={`${m.name} ${m.id}`} onSelect={() => go(`/metrics#metric-${m.id}`)} className={item}>
              <BarChart3 className="h-4 w-4 text-muted-2" />
              {m.name}
              <span className="ml-auto font-mono text-[11px] text-muted-2">{m.id}</span>
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading="Threads" className={group}>
          {sessions.map((s) => (
            <Command.Item key={s.id} value={`thread ${s.title}`} onSelect={() => go(`/ask/${s.id}`)} className={item}>
              <MessageCircle className="h-4 w-4 text-muted-2" />
              {s.title || 'Untitled chat'}
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading="Go to" className={group}>
          {PAGES.map((p) => (
            <Command.Item key={p.to} value={`page ${p.label}`} onSelect={() => go(p.to)} className={item}>
              {p.label}
            </Command.Item>
          ))}
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}

/** Sidebar affordance that opens the palette (dispatches the same hotkey). */
export function CommandTrigger() {
  return (
    <button
      type="button"
      onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))}
      className="mt-2 flex w-full items-center gap-2 rounded-md border border-border/70 bg-card/60 px-2.5 py-1.5 text-label text-muted-foreground transition-colors hover:text-ink"
    >
      <Search className="h-3.5 w-3.5" />
      Search
      <kbd className="ml-auto font-mono text-[10.5px] text-muted-2">⌘K</kbd>
    </button>
  );
}
```

```ts
// src/features/command/index.ts
// Public interface of the command feature.
export { CommandPalette, CommandTrigger } from './command-palette';
```

- [ ] **Step 4: Run → PASS, commit**

Run: `corepack pnpm vitest run src/features/command` → PASS

```bash
git add src/features/command vitest.setup.ts
git commit -m "feat(command): Spotlight-style ⌘K palette"
```

---

### Task 5: Wire into the app

**Files:** Modify `src/App.tsx`

- [ ] **Step 1: Edit**

Imports:
```tsx
import { Library } from 'lucide-react';
import { MetricsPage } from '@/features/metrics';
import { CommandPalette, CommandTrigger } from '@/features/command';
```
Add to `NAV` (after Ask Atlas): `{ to: '/metrics', label: 'Metrics', icon: Library },`.
In `AppShell`, pass `threads={<><CommandTrigger /><ChatThreadList /></>}` and render `<CommandPalette />` next to `<Outlet />`:
```tsx
    <Shell user={user} onSignOut={() => void signOut()} nav={NAV} threads={<><CommandTrigger /><ChatThreadList /></>}>
      <Outlet />
      <CommandPalette />
    </Shell>
```
Add the route inside the layout route: `<Route path="metrics" element={<MetricsPage />} />`.

- [ ] **Step 2: Gate + visual check**

Run: `corepack pnpm test && corepack pnpm lint && corepack pnpm typecheck`
Expected: PASS.

Then run the app and check against reference Mode ①, cases 8 and 9:
- the catalog renders the grouped list, rows expand on a spring, and `#metric-…` deep links open the row
- ⌘K materializes over the scrim, typing filters, Enter on "Ask: …" opens chat and sends
- light, dark and reduced-transparency all look right

- [ ] **Step 3: Commit**

```bash
git add src/App.tsx
git commit -m "feat(app): metrics route, nav entry and ⌘K palette"
```

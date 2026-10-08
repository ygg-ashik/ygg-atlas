# Hybrid Glass Track D2: Answer Blocks UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the structured answer blocks from Track C:
- **clarify** becomes choice pills, so the user picks instead of the agent guessing (guardrail #1 made visible).
- **artifact** becomes an inline card that opens a right-hand side panel with a chart, a table, provenance and CSV export (Claude artifact pattern).

**Architecture:** All work is inside `features/chat`, building on Track B's panel. Pure helpers (`csv.ts`, `artifact-series.ts`) are unit-tested. `ClarifyBlock`, `ArtifactCard` and `ArtifactPanel` are presentational. `chat-panel.tsx` owns the "open artifact" state and becomes a two-column layout. The panel enters from the right and leaves the same way (spring width), and becomes an overlay sheet below 1200px.

**Tech Stack:** React 19, `motion/react`, Vitest.

**Depends on:**
- Track B merged (chat panel, notices, provenance chips).
- Track C contract (`AnswerBlock` types in `src/api/chat.ts`). If C hasn't merged yet, copy Track C Task 6's type additions first; they're identical.

**Branch/worktree:** `feature/hybrid-glass-d2` · from `frontend/`.

---

## File map (`src/features/chat/`)

| File | Change | Responsibility |
|---|---|---|
| `csv.ts` (+ test) | Create | Artifact → CSV string, safe filename |
| `artifact-series.ts` (+ test) | Create | Pick label/value columns for the bar chart |
| `clarify-block.tsx` (+ test) | Create | Question + option pills (active only on the latest answer) |
| `artifact-card.tsx` | Create | Inline card that opens the panel |
| `artifact-panel.tsx` (+ test) | Create | Side panel: title, provenance, bars, table, export |
| `chat-panel.tsx` | Modify | Render blocks; two-column layout with panel |

---

### Task 1: Pure helpers

**Files:** Create `csv.ts`, `csv.test.ts`, `artifact-series.ts`, `artifact-series.test.ts`

- [ ] **Step 1: Failing tests**

```ts
// src/features/chat/csv.test.ts
import { describe, expect, it } from 'vitest';
import { artifactFilename, toCsv } from './csv';

describe('csv', () => {
  it('quotes cells with commas, quotes and newlines; nulls are empty', () => {
    expect(toCsv(['Label', 'Value'], [['b2b, corp', 1000], ['say "hi"', null], ['a\nb', 2]])).toBe(
      'Label,Value\r\n"b2b, corp",1000\r\n"say ""hi""",\r\n"a\nb",2',
    );
  });
  it('neutralizes spreadsheet formula injection', () => {
    expect(toCsv(['x'], [['=HYPERLINK("evil")'], ['+1'], ['-2'], ['@a']])).toBe('x\r\n"\'=HYPERLINK(""evil"")"\r\n\'+1\r\n\'-2\r\n\'@a');
  });
  it('builds a safe filename', () => {
    expect(artifactFilename('Revenue: breakdown / Q3')).toBe('revenue-breakdown-q3.csv');
  });
});
```

```ts
// src/features/chat/artifact-series.test.ts
import { describe, expect, it } from 'vitest';
import { seriesFor } from './artifact-series';
import type { ArtifactBlock } from '@/api/chat';

const base = { kind: 'artifact', id: 'x', title: 't', unit: 'AED', provenance: { tool: 't', source: 's', executed_at: 'e' } } as const;

describe('seriesFor', () => {
  it('breakdown: label + value', () => {
    const a: ArtifactBlock = { ...base, artifact_type: 'breakdown', columns: ['Label', 'Value'], rows: [['b2b', 1000], ['b2c', 500]] };
    expect(seriesFor(a)).toEqual([{ label: 'b2b', value: 1000 }, { label: 'b2c', value: 500 }]);
  });
  it('comparison: period + value column', () => {
    const a: ArtifactBlock = { ...base, artifact_type: 'comparison', columns: ['Period', 'Start', 'End', 'Value'],
      rows: [['A', '2026-09-01', '2026-09-30', 120], ['B', '2026-08-01', '2026-08-31', 100]] };
    expect(seriesFor(a)).toEqual([{ label: 'A · 2026-09-01 → 2026-09-30', value: 120 }, { label: 'B · 2026-08-01 → 2026-08-31', value: 100 }]);
  });
  it('funnel: step + users; non-numeric values are dropped', () => {
    const a: ArtifactBlock = { ...base, artifact_type: 'funnel', columns: ['Step', 'Users', 'Conversion from previous %'],
      rows: [['View', 100, null], ['Cart', 60, 60], ['Bad', null, null]] };
    expect(seriesFor(a)).toEqual([{ label: 'View', value: 100 }, { label: 'Cart', value: 60 }]);
  });
});
```

- [ ] **Step 2: Run → FAIL**

Run: `corepack pnpm vitest run src/features/chat/csv.test.ts src/features/chat/artifact-series.test.ts`

- [ ] **Step 3: Implement**

```ts
// src/features/chat/csv.ts
type Cell = string | number | null;

function cell(value: Cell): string {
  if (value === null) return '';
  let s = String(value);
  // CSV formula injection: prefix cells a spreadsheet would evaluate.
  if (typeof value === 'string' && /^[=+\-@]/.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(columns: string[], rows: Cell[][]): string {
  return [columns, ...rows].map((r) => r.map(cell).join(',')).join('\r\n');
}

export function artifactFilename(title: string): string {
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return `${slug || 'artifact'}.csv`;
}
```

```ts
// src/features/chat/artifact-series.ts
import type { ArtifactBlock } from '@/api/chat';

export interface SeriesPoint {
  label: string;
  value: number;
}

/** Which columns become the bar chart, per artifact type (built from tool output). */
export function seriesFor(artifact: ArtifactBlock): SeriesPoint[] {
  const points = artifact.rows.map((r): SeriesPoint | null => {
    if (artifact.artifact_type === 'comparison') {
      const [period, start, end, value] = r;
      return typeof value === 'number' ? { label: `${period} · ${start} → ${end}`, value } : null;
    }
    const [label, value] = r;
    return typeof value === 'number' ? { label: String(label), value } : null;
  });
  return points.filter((p): p is SeriesPoint => p !== null);
}
```

- [ ] **Step 4: Run → PASS, commit**

```bash
git add src/features/chat/csv.ts src/features/chat/csv.test.ts src/features/chat/artifact-series.ts src/features/chat/artifact-series.test.ts
git commit -m "feat(chat): artifact CSV export and chart series helpers"
```

---

### Task 2: Clarify block

**Files:** Create `clarify-block.tsx`, `clarify-block.test.tsx`

- [ ] **Step 1: Failing test**

```tsx
// src/features/chat/clarify-block.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ClarifyBlock } from './clarify-block';

const block = {
  kind: 'clarify' as const,
  question: 'Which revenue do you mean?',
  options: [{ label: 'Corporate revenue', metric_id: 'b2b_revenue' }, { label: 'All revenue', metric_id: 'revenue' }],
};

describe('ClarifyBlock', () => {
  it('sends the chosen option and marks it selected', async () => {
    const onChoose = vi.fn();
    render(<ClarifyBlock block={block} active onChoose={onChoose} />);
    expect(screen.getByRole('group', { name: 'Which revenue do you mean?' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Corporate revenue' }));
    expect(onChoose).toHaveBeenCalledWith('Corporate revenue');
    expect(screen.getByRole('button', { name: 'Corporate revenue' })).toHaveAttribute('data-selected', 'true');
  });

  it('is inert once the conversation moved on', () => {
    render(<ClarifyBlock block={block} active={false} onChoose={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'All revenue' })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement**

```tsx
// src/features/chat/clarify-block.tsx
import { useState } from 'react';
import { Button } from '@/ui';
import type { ClarifyBlock as ClarifyBlockData } from '@/api/chat';

interface ClarifyBlockProps {
  block: ClarifyBlockData;
  /** Only the latest answer's clarification is actionable. */
  active: boolean;
  onChoose: (label: string) => void;
}

/** Clarify instead of guess (guardrail #1). Choice pills (DESIGN.md › Clarify). */
export function ClarifyBlock({ block, active, onChoose }: ClarifyBlockProps) {
  const [chosen, setChosen] = useState<string | null>(null);
  return (
    <div role="group" aria-label={block.question} className="my-2.5 flex flex-wrap gap-2">
      {block.options.map((o) => (
        <Button
          key={o.label}
          variant="pill"
          data-selected={chosen === o.label}
          disabled={!active || chosen !== null}
          onClick={() => {
            setChosen(o.label);
            onChoose(o.label);
          }}
        >
          {o.label}
        </Button>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run → PASS, commit**

```bash
git add src/features/chat/clarify-block.tsx src/features/chat/clarify-block.test.tsx
git commit -m "feat(chat): clarify choice pills"
```

---

### Task 3: Artifact card + side panel

**Files:** Create `artifact-card.tsx`, `artifact-panel.tsx`, `artifact-panel.test.tsx`

- [ ] **Step 1: Failing test**

```tsx
// src/features/chat/artifact-panel.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ArtifactPanel } from './artifact-panel';
import type { ArtifactBlock } from '@/api/chat';

const artifact: ArtifactBlock = {
  kind: 'artifact', id: 'metric_breakdown:revenue:1', artifact_type: 'breakdown', title: 'Revenue: breakdown', unit: 'AED',
  columns: ['Label', 'Value'], rows: [['b2b', 1000], ['b2c', 500]],
  provenance: { tool: 'metric_breakdown', source: 'demo', metric_id: 'revenue', metric_name: 'Revenue', executed_at: '2026-10-08T00:00:00Z' },
};

describe('ArtifactPanel', () => {
  it('shows title, provenance, chart bars and a tabular table', () => {
    render(<ArtifactPanel artifact={artifact} onClose={vi.fn()} />);
    expect(screen.getByRole('heading', { name: 'Revenue: breakdown' })).toHaveClass('font-serif');
    expect(screen.getByText(/demo/)).toBeInTheDocument();
    expect(screen.getAllByTestId('artifact-bar')).toHaveLength(2);
    expect(screen.getByRole('table')).toHaveClass('tabular');
  });

  it('exports CSV and closes', async () => {
    const onClose = vi.fn();
    const createObjectURL = vi.fn(() => 'blob:x');
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    render(<ArtifactPanel artifact={artifact} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: /Export CSV/ }));
    expect(createObjectURL).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole('button', { name: 'Close artifact' }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement**

```tsx
// src/features/chat/artifact-card.tsx
import { ArrowRight, Table2 } from 'lucide-react';
import type { ArtifactBlock } from '@/api/chat';

/** Inline card linking to the artifact side panel (DESIGN.md › artifact-card). */
export function ArtifactCard({ artifact, onOpen }: { artifact: ArtifactBlock; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="my-2.5 flex w-full items-center gap-3 rounded-card bg-card px-3.5 py-3 text-left shadow-[0_0_0_1px_hsl(var(--border)/0.6)] transition-[box-shadow,transform] duration-300 ease-out hover:shadow-[0_0_0_1px_hsl(var(--border)),0_8px_24px_rgba(0,0,0,0.08)] active:scale-[.99]"
    >
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[11px] bg-primary/10 text-primary-text">
        <Table2 className="h-[18px] w-[18px]" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold text-ink">{artifact.title}</span>
        <span className="block text-caption text-muted-foreground">Chart + table · opens in side panel</span>
      </span>
      <ArrowRight className="h-4 w-4 text-muted-2" />
    </button>
  );
}
```

```tsx
// src/features/chat/artifact-panel.tsx
import { Download, X } from 'lucide-react';
import { Button } from '@/ui';
import type { ArtifactBlock } from '@/api/chat';
import { ProvenanceChips } from './provenance-chips';
import { artifactFilename, toCsv } from './csv';
import { seriesFor } from './artifact-series';

const fmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

function exportCsv(artifact: ArtifactBlock) {
  const blob = new Blob([toCsv(artifact.columns, artifact.rows)], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = artifactFilename(artifact.title);
  a.click();
  URL.revokeObjectURL(url);
}

/** Claude-style artifact panel: data on a solid surface, never on glass. */
export function ArtifactPanel({ artifact, onClose }: { artifact: ArtifactBlock; onClose: () => void }) {
  const series = seriesFor(artifact);
  const max = Math.max(...series.map((p) => p.value), 1);
  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto rounded-shell bg-card px-5 py-[18px] shadow-[0_0_0_1px_hsl(var(--border)),0_20px_60px_rgba(0,0,0,0.14)]">
      <div className="flex items-start gap-2.5">
        <h3 className="min-w-0 flex-1 font-serif text-title text-ink">{artifact.title}</h3>
        <Button variant="ghost" size="icon" aria-label="Close artifact" onClick={onClose}>
          <X />
        </Button>
      </div>
      <ProvenanceChips provenance={[artifact.provenance]} />
      {series.length > 0 && (
        <div className="space-y-1.5 py-1" aria-hidden>
          {series.map((p, i) => (
            <div key={p.label} className="grid grid-cols-[minmax(0,40%)_1fr] items-center gap-3 text-caption text-muted-foreground">
              <span className="truncate">{p.label}</span>
              <div className="h-4 overflow-hidden rounded-md bg-primary/10">
                <div
                  data-testid="artifact-bar"
                  className="h-full origin-left animate-[grow_900ms_cubic-bezier(.22,1,.36,1)_both] rounded-md bg-primary"
                  style={{ width: `${(p.value / max) * 100}%`, opacity: 1 - i * (0.55 / Math.max(series.length, 1)), animationDelay: `${i * 60}ms` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="max-w-full overflow-x-auto">
        <table className="tabular w-full text-[13.5px]">
          <thead>
            <tr>
              {artifact.columns.map((c, i) => (
                <th key={c} className={`border-b border-border px-1 py-2 text-caption font-medium text-muted-foreground ${i > 0 ? 'text-right' : 'text-left'}`}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {artifact.rows.map((r, ri) => (
              <tr key={ri} className="border-b border-border/50 last:border-0">
                {r.map((v, ci) => (
                  <td key={ci} className={`px-1 py-2 ${ci > 0 ? 'text-right text-ink' : 'text-body'}`}>
                    {typeof v === 'number' ? fmt.format(v) : (v ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {artifact.unit && <p className="text-caption text-muted-2">Values in {artifact.unit}.</p>}
      <div className="mt-auto flex gap-2 pt-2">
        <Button variant="pill" size="sm" onClick={() => exportCsv(artifact)}>
          <Download /> Export CSV
        </Button>
      </div>
    </div>
  );
}
```

If Track E-fe hasn't added the `grow` keyframe to `tailwind.config.js` yet, add it now (same definition as dashboard plan Task 4).

- [ ] **Step 4: Run → PASS, commit**

```bash
corepack pnpm vitest run src/features/chat/artifact-panel.test.tsx
git add src/features/chat/artifact-card.tsx src/features/chat/artifact-panel.tsx src/features/chat/artifact-panel.test.tsx tailwind.config.js
git commit -m "feat(chat): artifact card and side panel with CSV export"
```

---

### Task 4: Wire blocks into the chat panel

**Files:** Modify `src/features/chat/chat-panel.tsx`; Modify `src/features/chat/chat-panel.test.tsx`

- [ ] **Step 1: Failing test** (append to `chat-panel.test.tsx`, overriding the messages mock for this case)

```tsx
  it('renders clarify pills and opens an artifact in the side panel', async () => {
    const { useChatMessages } = await import('@/api/hooks/use-chat-sessions');
    vi.mocked(useChatMessages).mockReturnValue({
      data: [
        { id: 'u1', role: 'user', content: 'split revenue', created_at: '' },
        {
          id: 'a1', role: 'assistant', content: 'Here is the split.', created_at: '', provenance: [],
          blocks: [
            { kind: 'clarify', question: 'Which period?', options: [{ label: 'Last 7 days' }, { label: 'Last 30 days' }] },
            { kind: 'artifact', id: 'x', artifact_type: 'breakdown', title: 'Revenue: breakdown', unit: 'AED',
              columns: ['Label', 'Value'], rows: [['b2b', 1000]], provenance: { tool: 'metric_breakdown', source: 'demo', executed_at: 't' } },
          ],
        },
      ],
    } as never);
    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Last 7 days' }));
    expect(send).toHaveBeenCalledWith('Last 7 days');
    await userEvent.click(screen.getByRole('button', { name: /Revenue: breakdown/ }));
    expect(await screen.findByRole('heading', { name: 'Revenue: breakdown' })).toBeInTheDocument();
  });
```

Change the file's messages mock to `vi.mock('@/api/hooks/use-chat-sessions', () => ({ useChatMessages: vi.fn(() => ({ data: [] })) }));` so it can be overridden.

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement in `chat-panel.tsx`**

Imports:
```tsx
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { EASE_SHEET, withReducedMotion } from '@/ui';
import type { ArtifactBlock } from '@/api/chat';
import { ClarifyBlock } from './clarify-block';
import { ArtifactCard } from './artifact-card';
import { ArtifactPanel } from './artifact-panel';
```

State + helpers inside `ChatPanel`:
```tsx
  const [openArtifact, setOpenArtifact] = useState<ArtifactBlock | null>(null);
  const reduced = useReducedMotion();
  const lastAssistantId = [...messages].reverse().find((m) => m.role === 'assistant')?.id;
```

Render blocks for each assistant message, right after `<MarkdownMessage text={m.content} />`:
```tsx
                  {m.blocks?.map((b) =>
                    b.kind === 'clarify' ? (
                      <ClarifyBlock
                        key={`clarify-${m.id}`}
                        block={b}
                        active={m.id === lastAssistantId && !isStreaming}
                        onChoose={(label) => sendText(label)}
                      />
                    ) : (
                      <ArtifactCard key={b.id} artifact={b} onOpen={() => setOpenArtifact(b)} />
                    ),
                  )}
```

Make the root a two-column layout. Wrap the existing root content (scroller, edge, composer) in `<div className="relative min-w-0 flex-1">…</div>` and change the root to `<div className="absolute inset-0 flex">`. Then add the panel as the last child:
```tsx
      <AnimatePresence initial={false}>
        {openArtifact && (
          <motion.aside
            key="artifact-panel"
            aria-label="Artifact"
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 'min(44vw, 540px)', opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={withReducedMotion({ duration: 0.55, ease: EASE_SHEET }, reduced)}
            className="relative shrink-0 overflow-hidden py-2.5 pr-2.5 max-[1199px]:absolute max-[1199px]:inset-y-0 max-[1199px]:right-0 max-[1199px]:z-30"
          >
            <div className="h-full w-[min(44vw,540px)] min-w-[320px]">
              <ArtifactPanel artifact={openArtifact} onClose={() => setOpenArtifact(null)} />
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
```
Below 1200px, also render a scrim when open:
`{openArtifact && <button aria-label="Close artifact panel" onClick={() => setOpenArtifact(null)} className="absolute inset-0 z-20 hidden bg-black/20 max-[1199px]:block" />}`

- [ ] **Step 4: Gate + visual check**

Run: `corepack pnpm test && corepack pnpm lint && corepack pnpm typecheck`
Expected: PASS.

Run the app with backend Tracks C + E-be merged. Compare with reference Mode ①, cases 3 and 4:
- **Ambiguous question** ("How did sales do?"): clarify pills appear. Picking one sends it, and older pills go inert.
- **Breakdown question:** an artifact card appears and the panel slides in from the right and leaves to the right. The table uses tabular figures and Export CSV downloads.
- **Narrow window:** the panel overlays with a scrim.
- **Settings:** dark mode and reduced-motion (instant panel) are correct.

- [ ] **Step 5: Commit**

```bash
git add src/features/chat
git commit -m "feat(chat): render clarify and artifact answer blocks"
```

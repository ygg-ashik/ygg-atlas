# Hybrid Glass Track B: Chat Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Follow the `engineering-standards` skill before writing code and the `production-code-review` skill before calling the track done. Gate: `make check` from the repo root (run `make format` first: the code below predates prettier/ruff formatting).

**Goal:** Rebuild the chat in Atlas Hybrid Glass:
- prose answers streamed with streamdown blur-in
- a Codex-style steps block that collapses into Claude's "Worked for Ns"
- a floating glass composer with send⇄stop and an elapsed timer
- provenance chips with a definition popover and staleness warnings
- notices that persist after the stream ends
- in-place feedback morphs

**Architecture:** All work is inside `src/features/chat` and uses Track A primitives from `@/ui` (`Glass`, `Toolbar`, `Popover`, `Button`, `PresetCard`, motion presets).
- **Pure logic** lives in small modules with unit tests: `steps.ts` and the `useChatTurn` state. Freshness helpers come from `@/lib/freshness` (Track A).
- **Components:**
  - `composer.tsx`
  - `steps-block.tsx`
  - `notice.tsx`
  - `message-actions.tsx`
  - `provenance-chips.tsx`
  - `markdown-message.tsx`
- **Wiring:** `chat-panel.tsx` composes the components above.
- **Streamdown** replaces `markdown-stream.ts`. Its animate plugin (word blur-in, 40ms stagger, 320ms backlog cap) provides the adaptive pacing from DESIGN.md.

**Tech Stack:** React 19, `streamdown`, `motion/react`, Radix popover, Vitest + Testing Library.

**Depends on:** Track A merged (`…-01-foundation.md`). **Branch/worktree:** `feature/hybrid-glass-b` · from `frontend/`.

> **Folder layout (ARCHITECTURE.md §3.2).** Track A Task 0 moves the chat feature into `components/` and
> `hooks/`. Paths in this plan are written flat (`src/features/chat/<file>`). Place each file as follows
> and use matching relative imports (`../hooks/use-chat-turn`, `../steps`, `./composer`):
>
> | Location | Files (tests sit next to their module) |
> |---|---|
> | `src/features/chat/components/` | `chat-panel`, `markdown-message`, `steps-block`, `composer`, `notice`, `provenance-chips`, `message-actions`, `chat-thread-list`, `clarify-block`, `artifact-card`, `artifact-panel` |
> | `src/features/chat/hooks/` | `use-chat-turn`, `use-stick-to-bottom` |
> | `src/features/chat/` (root) | `index.tsx`, `steps.ts`, `chat-suggestions.ts`, `csv.ts`, `artifact-series.ts` |
>
> `chat-panel.tsx` was split by the standards change into `EmptyState` / `StoredMessage` / `DraftView` /
> `Composer` to keep complexity ≤ 12. Keep that decomposition: put each in its own file under
> `components/` (`empty-state.tsx`, `stored-message.tsx`, `draft-view.tsx`; the composer is this plan's
> `composer.tsx`). `ChatPanel` stays a thin layout that composes them. Lint limits: ≤300 lines/file,
> ≤150 lines/function, complexity ≤12, ≤4 params, no nested ternaries, `noUncheckedIndexedAccess`.

---

## File map (`src/features/chat/`)

| File | Change | Responsibility |
|---|---|---|
| `steps.ts` (+ test) | Create | Step model, reducer helpers, human labels, steps from provenance |
| `use-chat-turn.ts` (+ test) | Modify | Track steps/timing, persistent `notice`, `lastTurn` |
| `use-stick-to-bottom.ts` (+ test) | Create | Auto-scroll only while near the bottom (240px) |
| `markdown-message.tsx` (+ test) | Rewrite | Streamdown renderer (streaming vs static) |
| `markdown-stream.ts` + test | Delete | Superseded by streamdown (cases ported to markdown-message test) |
| `steps-block.tsx` (+ test) | Create | Live plan → "Worked for Ns · N steps" collapse |
| `composer.tsx` (+ test) | Create | Glass composer, send⇄stop, elapsed timer |
| `notice.tsx` (+ test) | Create | blocked / error (retry) / stale notices |
| `provenance-chips.tsx` (+ test) | Rewrite | Chips + glass definition popover + amber when stale |
| `message-actions.tsx` (+ test) | Create (replaces `message-feedback.tsx`) | Copy→✓ morph, thumbs fill, categories |
| `chat-suggestions.ts` | Rewrite | `CHAT_PRESETS` for the empty-state preset gallery |
| `chat-panel.tsx` | Rewrite | Layout, empty state, history, draft, glide composer |
| `/DESIGN.md` | Modify | Streaming section: pacing implemented via streamdown animate |

---

### Task 1: Steps model

**Files:** Create `src/features/chat/steps.ts`, `src/features/chat/steps.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
// src/features/chat/steps.test.ts
import { describe, expect, it } from 'vitest';
import { applyToolStatus, completeAll, stepLabel, stepsFromProvenance, type Step } from './steps';

describe('steps', () => {
  it('a new tool completes the running one and starts itself', () => {
    let steps: Step[] = [];
    steps = applyToolStatus(steps, 'search_atlas');
    expect(steps).toEqual([{ tool: 'search_atlas', status: 'running' }]);
    steps = applyToolStatus(steps, 'query_metric');
    expect(steps).toEqual([
      { tool: 'search_atlas', status: 'done' },
      { tool: 'query_metric', status: 'running' },
    ]);
  });

  it('completeAll finishes every step and is a no-op on empty', () => {
    expect(completeAll([{ tool: 'a', status: 'running' }])).toEqual([{ tool: 'a', status: 'done' }]);
    expect(completeAll([])).toEqual([]);
  });

  it('labels tools in business language and falls back to the id', () => {
    expect(stepLabel('query_metric')).toBe('Querying a governed metric');
    expect(stepLabel('ask_clarification')).toBe('Preparing a clarifying question');
    expect(stepLabel('mystery_tool')).toBe('mystery_tool');
  });

  it('derives completed steps from persisted provenance (one per tool + metric)', () => {
    const prov = [
      { tool: 'query_metric', metric_id: 'revenue', source: 'demo', executed_at: 't1' },
      { tool: 'query_metric', metric_id: 'revenue', source: 'demo', executed_at: 't2' },
      { tool: 'compare_periods', metric_id: 'revenue', source: 'demo', executed_at: 't3' },
    ];
    expect(stepsFromProvenance(prov)).toEqual([
      { tool: 'query_metric', status: 'done' },
      { tool: 'compare_periods', status: 'done' },
    ]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `corepack pnpm vitest run src/features/chat/steps.test.ts`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

```ts
// src/features/chat/steps.ts
// The steps block (DESIGN.md › plan-block) is derived from tool_status events
// live, and from provenance for persisted answers. No extra backend events.
import type { Provenance } from '@/api/chat';

export interface Step {
  tool: string;
  status: 'running' | 'done';
}

const LABELS: Record<string, string> = {
  search_atlas: 'Searching the atlas',
  list_metrics: 'Listing governed metrics',
  describe_entity: 'Reading a data definition',
  query_metric: 'Querying a governed metric',
  metric_breakdown: 'Breaking the metric down',
  compare_periods: 'Comparing periods',
  funnel_analyze: 'Analyzing the funnel',
  ask_clarification: 'Preparing a clarifying question',
};

export function stepLabel(tool: string): string {
  return LABELS[tool] ?? tool;
}

export function applyToolStatus(steps: Step[], tool: string): Step[] {
  return [...completeAll(steps), { tool, status: 'running' }];
}

export function completeAll(steps: Step[]): Step[] {
  return steps.map((s) => (s.status === 'done' ? s : { ...s, status: 'done' }));
}

export function stepsFromProvenance(provenance: Provenance[]): Step[] {
  const seen = new Set<string>();
  const steps: Step[] = [];
  for (const p of provenance) {
    const key = `${p.tool}::${p.metric_id ?? ''}`;
    if (seen.has(key)) continue;
    seen.add(key);
    steps.push({ tool: p.tool, status: 'done' });
  }
  return steps;
}
```

- [ ] **Step 4: Run + commit**

Run: `corepack pnpm vitest run src/features/chat/steps.test.ts` → PASS

```bash
git add src/features/chat/steps.ts src/features/chat/steps.test.ts
git commit -m "feat(chat): steps model derived from tool_status and provenance"
```

---

### Task 2: (moved) Freshness helpers

Freshness helpers are built in Track A (`…-01-foundation.md` Task 13) as `src/lib/freshness.ts`, so the
dashboard track can share them. Import them from `@/lib/freshness`. Nothing to do here.

---

### Task 3: `useChatTurn` tracks steps, timing, persistent notice, last turn

**Files:** Modify `src/features/chat/use-chat-turn.ts`, `src/features/chat/use-chat-turn.test.tsx`

- [ ] **Step 1: Add failing tests** (append inside `describe('useChatTurn')`; reuse the file's `deferredStream` + `wrapper`)

```tsx
  it('records steps from tool_status and completes them on tokens', async () => {
    const stream = deferredStream();
    const { result } = renderHook(() => useChatTurn('sess-1'), { wrapper });
    act(() => void result.current.send('q'));
    await waitFor(() => expect(result.current.isStreaming).toBe(true));
    expect(typeof result.current.draft?.startedAt).toBe('number');

    act(() => stream.emit({ type: 'tool_status', tool: 'search_atlas' }));
    act(() => stream.emit({ type: 'tool_status', tool: 'query_metric' }));
    expect(result.current.draft?.steps).toEqual([
      { tool: 'search_atlas', status: 'done' },
      { tool: 'query_metric', status: 'running' },
    ]);
    act(() => stream.emit({ type: 'token', content: 'Revenue' }));
    expect(result.current.draft?.steps.every((s) => s.status === 'done')).toBe(true);
    act(() => stream.finish());
    await waitFor(() => expect(result.current.isStreaming).toBe(false));
  });

  it('keeps lastTurn (steps + duration) for the persisted message after done', async () => {
    const stream = deferredStream();
    const { result } = renderHook(() => useChatTurn('sess-1'), { wrapper });
    act(() => void result.current.send('q'));
    await waitFor(() => expect(result.current.isStreaming).toBe(true));
    act(() => stream.emit({ type: 'tool_status', tool: 'query_metric' }));
    act(() => stream.emit({ type: 'done', content: 'ok', provenance: [], message_id: 'm-9' }));
    act(() => stream.finish());
    await waitFor(() => expect(result.current.draft).toBeNull());
    expect(result.current.lastTurn).toMatchObject({
      messageId: 'm-9',
      steps: [{ tool: 'query_metric', status: 'done' }],
    });
    expect(result.current.lastTurn?.durationMs).toBeGreaterThanOrEqual(0);
  });

  it('keeps an error notice with retry text after the draft clears', async () => {
    const stream = deferredStream();
    const { result } = renderHook(() => useChatTurn('sess-1'), { wrapper });
    act(() => void result.current.send('why did revenue drop?'));
    await waitFor(() => expect(result.current.isStreaming).toBe(true));
    act(() => stream.emit({ type: 'error', message: 'Something went wrong.' }));
    act(() => stream.finish());
    await waitFor(() => expect(result.current.draft).toBeNull());
    expect(result.current.notice).toEqual({
      kind: 'error',
      message: 'Something went wrong.',
      retryText: 'why did revenue drop?',
    });
  });

  it('clears the notice on the next send', async () => {
    const stream = deferredStream();
    const { result } = renderHook(() => useChatTurn('sess-1'), { wrapper });
    act(() => void result.current.send('a'));
    await waitFor(() => expect(result.current.isStreaming).toBe(true));
    act(() => stream.emit({ type: 'blocked', reason: 'Daily limit reached.' }));
    act(() => stream.finish());
    await waitFor(() => expect(result.current.notice?.kind).toBe('blocked'));
    deferredStream();
    act(() => void result.current.send('b'));
    expect(result.current.notice).toBeNull();
  });
```

- [ ] **Step 2: Run to verify failure**

Run: `corepack pnpm vitest run src/features/chat/use-chat-turn.test.tsx`
Expected: the 4 new tests FAIL (`steps`, `startedAt`, `lastTurn`, `notice` undefined). Existing tests still pass.

- [ ] **Step 3: Implement**

Add to imports: `import { applyToolStatus, completeAll, type Step } from './steps';`

Extend the types:
```ts
export interface DraftTurn {
  userText: string;
  assistantText: string;
  toolStatus: string | null;
  notice: string | null; // blocked/error text (kept for compatibility)
  phase: 'thinking' | 'streaming' | null;
  provenance: Provenance[] | null;
  steps: Step[];
  startedAt: number;
}

export interface TurnNotice {
  kind: 'blocked' | 'error';
  message: string;
  retryText: string;
}

export interface LastTurn {
  messageId: string;
  steps: Step[];
  durationMs: number;
}
```

In the hook body add state:
```ts
  const [notice, setNotice] = useState<TurnNotice | null>(null);
  const [lastTurn, setLastTurn] = useState<LastTurn | null>(null);
```

In `send`, right after the `isStreaming` guard: `setNotice(null);`. The initial `setDraft({...})` gains `steps: [], startedAt: Date.now(),`. Add a local `const raise = (kind: TurnNotice['kind'], message: string) => setNotice({ kind, message, retryText: content });` and call it everywhere a draft notice is set (session-creation failure → `raise('error', 'Could not start a chat. Please try again.')`, connection-lost catch → `raise('error', 'Connection lost. Please try again.')`).

Replace the event switch body:
```ts
              switch (event.type) {
                case 'token':
                  return {
                    ...d,
                    assistantText: d.assistantText + event.content,
                    toolStatus: null,
                    phase: 'streaming' as const,
                    steps: completeAll(d.steps),
                  };
                case 'tool_status':
                  return { ...d, toolStatus: event.tool, steps: applyToolStatus(d.steps, event.tool) };
                case 'done': {
                  const steps = completeAll(d.steps);
                  if (event.message_id) {
                    setLastTurn({ messageId: event.message_id, steps, durationMs: Date.now() - d.startedAt });
                  }
                  return {
                    ...d,
                    assistantText: event.content,
                    toolStatus: null,
                    phase: null,
                    provenance: event.provenance ?? null,
                    steps,
                  };
                }
                case 'blocked':
                  raise('blocked', event.reason);
                  return { ...d, notice: event.reason, toolStatus: null, phase: null };
                case 'error':
                  raise('error', event.message);
                  return { ...d, notice: event.message, toolStatus: null, phase: null };
                default:
                  return d;
              }
```

Return `{ draft, isStreaming, send, abort, notice, lastTurn }`.

- [ ] **Step 4: Run tests**

Run: `corepack pnpm vitest run src/features/chat/use-chat-turn.test.tsx` → PASS (old + new)

- [ ] **Step 5: Commit**

```bash
git add src/features/chat/use-chat-turn.ts src/features/chat/use-chat-turn.test.tsx
git commit -m "feat(chat): turn steps, timing, persistent notice and lastTurn"
```

---

### Task 4: Streamdown markdown renderer (replaces markdown-stream)

**Files:** Rewrite `src/features/chat/markdown-message.tsx`; Create `src/features/chat/markdown-message.test.tsx`; Delete `markdown-stream.ts`, `markdown-stream.test.ts`; Modify `/DESIGN.md`

- [ ] **Step 1: Write failing tests** (port the old stabilizer cases as acceptance tests)

```tsx
// src/features/chat/markdown-message.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MarkdownMessage } from './markdown-message';

describe('MarkdownMessage', () => {
  it('renders complete markdown with bold and inline code', () => {
    render(<MarkdownMessage text="Revenue was **AED 1.2M** (`revenue_total`)." />);
    expect(screen.getByText('AED 1.2M').tagName).toMatch(/STRONG|SPAN/);
    expect(screen.getByText('revenue_total')).toBeInTheDocument();
  });

  it.each([
    ['unclosed bold', 'Revenue was **AED 1.2'],
    ['unclosed code', 'See `revenue_tot'],
    ['incomplete link', 'See [the dashboard](https://exa'],
  ])('never shows raw markdown syntax while streaming (%s)', (_name, text) => {
    const { container } = render(<MarkdownMessage text={text} streaming />);
    expect(container.textContent).not.toMatch(/\*\*|`|\]\(/);
  });

  it('renders external links in a new tab and neutralizes others', () => {
    render(<MarkdownMessage text="[docs](https://example.com) and [x](javascript:alert(1))" />);
    const link = screen.getByRole('link', { name: 'docs' });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
    expect(screen.queryByRole('link', { name: 'x' })).toBeNull();
  });

  it('wraps GFM tables in a horizontal scroller', () => {
    const { container } = render(<MarkdownMessage text={'| a | b |\n| - | - |\n| 1 | 2 |'} />);
    expect(container.querySelector('table')).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `corepack pnpm vitest run src/features/chat/markdown-message.test.tsx`
Expected: FAIL on `streaming` prop / raw markers (the old component has no streaming mode).

- [ ] **Step 3: Rewrite `markdown-message.tsx`**

```tsx
import { useReducedMotion } from 'motion/react';
import { Streamdown } from 'streamdown';

interface MarkdownMessageProps {
  text: string;
  /** True while tokens are still arriving. Enables incomplete-markdown repair,
   * word blur-in (DESIGN.md › Streaming) and the caret. */
  streaming?: boolean;
}

// DESIGN.md › Streaming: word chunks fade in from blur(3px) over 420ms. The
// animate plugin staggers words 40ms apart and caps the backlog at 320ms, which
// is the adaptive pacing (bursty network chunks flow out evenly).
const STREAM_ANIMATION = {
  animation: 'blurIn',
  sep: 'word',
  duration: 420,
  stagger: 40,
  maxBacklogMs: 320,
  easing: 'cubic-bezier(.22,1,.36,1)',
} as const;

/** Assistant prose: GFM, no raw HTML, safe links. Text already on screen never re-animates. */
export function MarkdownMessage({ text, streaming = false }: MarkdownMessageProps) {
  const reduced = useReducedMotion();
  return (
    <Streamdown
      mode={streaming ? 'streaming' : 'static'}
      isAnimating={streaming}
      parseIncompleteMarkdown
      animated={streaming && !reduced ? STREAM_ANIMATION : false}
      caret={streaming ? 'circle' : undefined}
      controls={{ table: false, code: { copy: true } }}
      className="min-w-0 text-answer text-body [&_h1]:mb-2.5 [&_h1]:mt-1.5 [&_h1]:font-serif [&_h1]:text-title [&_h1]:text-ink [&_h2]:mb-2.5 [&_h2]:mt-1.5 [&_h2]:font-serif [&_h2]:text-title [&_h2]:text-ink [&_h3]:mb-1.5 [&_h3]:mt-3 [&_h3]:font-serif [&_h3]:text-section [&_h3]:text-ink [&_li]:my-0.5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:mb-3 [&_strong]:font-semibold [&_strong]:text-ink [&_table]:tabular [&_td]:border-b [&_td]:px-2 [&_td]:py-1.5 [&_th]:border-b [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_th]:text-label [&_th]:font-medium [&_th]:text-muted-foreground [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5"
      components={{
        a: ({ href, children }) =>
          href && /^https?:\/\//.test(href) ? (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary-text underline underline-offset-2">
              {children}
            </a>
          ) : (
            <span>{children}</span>
          ),
        table: ({ children }) => (
          <div className="my-3 max-w-full overflow-x-auto rounded-lg bg-card shadow-[0_0_0_1px_hsl(var(--border)/0.6)]">
            <table className="w-max min-w-full">{children}</table>
          </div>
        ),
      }}
    >
      {text}
    </Streamdown>
  );
}
```

- [ ] **Step 4: Delete the superseded module**

```bash
git rm src/features/chat/markdown-stream.ts src/features/chat/markdown-stream.test.ts
```
(`chat-panel.tsx` still imports `stabilizeStreamingMarkdown` until Task 9. Temporarily replace that call with plain `draft.assistantText` so typecheck stays green.)

- [ ] **Step 5: Update DESIGN.md › Motion › Streaming** (replace the "Adaptive pacing" bullet)

```
- **Adaptive pacing:** implemented by `streamdown`'s animate plugin. Words are staggered 40ms apart and the
  scheduling backlog is capped at 320ms, so bursty network chunks flow out evenly and never fall far behind.
```
Then run `npx @google/design.md lint DESIGN.md` from the repo root. Expected: 0 errors.

- [ ] **Step 6: Run tests + typecheck**

Run: `corepack pnpm vitest run src/features/chat && corepack pnpm typecheck`
Expected: PASS. If a test can't find text because streamdown splits words into animation spans, assert on `container.textContent` instead of `getByText`. Don't weaken what the test checks.

- [ ] **Step 7: Commit**

```bash
git add -A src/features/chat ../DESIGN.md
git commit -m "feat(chat): streamdown blur-in streaming replaces markdown-stream"
```

---

### Task 5: Steps block

**Files:** Create `src/features/chat/steps-block.tsx`, `src/features/chat/steps-block.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// src/features/chat/steps-block.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { StepsBlock } from './steps-block';

describe('StepsBlock', () => {
  it('while working: shows each step with its mono tool id', () => {
    render(
      <StepsBlock
        live
        steps={[
          { tool: 'search_atlas', status: 'done' },
          { tool: 'query_metric', status: 'running' },
        ]}
      />,
    );
    expect(screen.getByText('Working · 2 steps')).toBeInTheDocument();
    expect(screen.getByText('Querying a governed metric')).toBeInTheDocument();
    expect(screen.getByText('query_metric')).toHaveClass('font-mono');
  });

  it('when finished: collapses to "Worked for Ns" and expands on click', async () => {
    render(<StepsBlock steps={[{ tool: 'query_metric', status: 'done' }]} durationMs={4200} />);
    const toggle = screen.getByRole('button', { name: /Worked for 4s · 1 step/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Querying a governed metric')).toBeVisible();
  });

  it('history without timing says how many atlas steps were used', () => {
    render(<StepsBlock steps={[{ tool: 'a', status: 'done' }, { tool: 'b', status: 'done' }]} />);
    expect(screen.getByRole('button', { name: /Used 2 atlas steps/ })).toBeInTheDocument();
  });

  it('renders nothing without steps', () => {
    const { container } = render(<StepsBlock steps={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run to verify failure** → FAIL (module not found)

- [ ] **Step 3: Implement**

```tsx
// src/features/chat/steps-block.tsx
import { useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Check, ChevronRight } from 'lucide-react';
import { cn, springDefault, withReducedMotion } from '@/ui';
import { stepLabel, type Step } from './steps';

interface StepsBlockProps {
  steps: Step[];
  /** Turn still in progress: list stays open, header shimmers. */
  live?: boolean;
  /** Known duration for the just-finished turn ("Worked for Ns"). */
  durationMs?: number;
}

const plural = (n: number) => `${n} step${n === 1 ? '' : 's'}`;

function stepsTitle(count: number, live: boolean, durationMs?: number): string {
  if (live) return `Working · ${plural(count)}`;
  if (durationMs !== undefined) {
    return `Worked for ${Math.max(1, Math.round(durationMs / 1000))}s · ${plural(count)}`;
  }
  return `Used ${count} atlas ${count === 1 ? 'step' : 'steps'}`;
}

/** Codex live plan → Claude "Worked for Ns" collapse (DESIGN.md › plan-block). */
export function StepsBlock({ steps, live = false, durationMs }: StepsBlockProps) {
  const [open, setOpen] = useState(false);
  const reduced = useReducedMotion();
  if (steps.length === 0) return null;

  const expanded = live || open;
  const title = stepsTitle(steps.length, live, durationMs);

  return (
    <div className="mb-3.5 rounded-lg bg-card px-3.5 py-3 shadow-[0_0_0_1px_hsl(var(--border)/0.6)]">
      <button
        type="button"
        aria-expanded={expanded}
        disabled={live}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 text-label text-muted-foreground"
      >
        <ChevronRight className={cn('h-3.5 w-3.5 transition-transform duration-300 ease-out', expanded && 'rotate-90')} />
        <span
          className={cn(
            live &&
              'animate-shimmer bg-[linear-gradient(90deg,hsl(var(--muted-foreground))_0%,hsl(var(--ink))_45%,hsl(var(--muted-foreground))_60%)] bg-[length:200%_100%] bg-clip-text text-transparent',
          )}
        >
          {title}
        </span>
      </button>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.ol
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={withReducedMotion(springDefault, reduced)}
            className="overflow-hidden"
          >
            {steps.map((s, i) => (
              <li key={`${s.tool}-${i}`} className="flex items-center gap-2.5 pt-1.5 text-label">
                {s.status === 'running' ? (
                  <span className="h-[15px] w-[15px] shrink-0 animate-spin rounded-full border-[1.5px] border-primary border-t-transparent" />
                ) : (
                  <span className="grid h-[15px] w-[15px] shrink-0 place-items-center rounded-[5px] bg-positive text-white">
                    <Check className="h-2.5 w-2.5" />
                  </span>
                )}
                <span className={s.status === 'done' ? 'text-body' : 'text-muted-foreground'}>{stepLabel(s.tool)}</span>
                <span className="ml-auto font-mono text-[11px] text-muted-2">{s.tool}</span>
              </li>
            ))}
          </motion.ol>
        )}
      </AnimatePresence>
    </div>
  );
}
```

- [ ] **Step 4: Run + commit**

Run: `corepack pnpm vitest run src/features/chat/steps-block.test.tsx` → PASS

```bash
git add src/features/chat/steps-block.tsx src/features/chat/steps-block.test.tsx
git commit -m "feat(chat): steps block with Worked-for collapse"
```

---

### Task 6: Composer

**Files:** Create `src/features/chat/composer.tsx`, `src/features/chat/composer.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// src/features/chat/composer.test.tsx
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Composer } from './composer';

const base = { value: '', onChange: vi.fn(), onSend: vi.fn(), onStop: vi.fn(), isStreaming: false, disabled: false };

describe('Composer', () => {
  afterEach(() => vi.useRealTimers());

  it('sends on Enter (not Shift+Enter) when there is text', () => {
    const onSend = vi.fn();
    render(<Composer {...base} value="revenue?" onSend={onSend} />);
    const box = screen.getByRole('textbox');
    fireEvent.keyDown(box, { key: 'Enter', shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(onSend).toHaveBeenCalledOnce();
  });

  it('morphs send into stop while streaming and shows the elapsed timer', () => {
    vi.useFakeTimers();
    const onStop = vi.fn();
    render(<Composer {...base} isStreaming startedAt={Date.now()} onStop={onStop} />);
    const stop = screen.getByRole('button', { name: 'Stop generating' });
    expect(stop).toHaveAttribute('data-streaming', 'true');
    act(() => vi.advanceTimersByTime(3_000));
    expect(screen.getByText('3s')).toHaveClass('font-mono');
    fireEvent.click(stop);
    expect(onStop).toHaveBeenCalledOnce();
  });

  it('is glass with the specular highlight', () => {
    render(<Composer {...base} />);
    expect(screen.getByRole('textbox').closest('form')).toHaveClass('glass', 'glass-specular', 'rounded-glass');
  });
});
```

- [ ] **Step 2: Run to verify failure** → FAIL

- [ ] **Step 3: Implement**

```tsx
// src/features/chat/composer.tsx
import { useEffect, useState } from 'react';
import { ArrowUp } from 'lucide-react';
import { Button, cn, Glass } from '@/ui';

interface ComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled: boolean;
  startedAt?: number;
}

function useElapsedSeconds(startedAt: number | undefined, active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return active && startedAt ? Math.max(0, Math.floor((now - startedAt) / 1000)) : 0;
}

/** Glass composer (DESIGN.md › glass-composer): send⇄stop morph with progress
 * ring, mono elapsed timer while working, accent focus ring. */
export function Composer({ value, onChange, onSend, onStop, isStreaming, disabled, startedAt }: ComposerProps) {
  const elapsed = useElapsedSeconds(startedAt, isStreaming);
  return (
    <Glass
      as="form"
      specular
      onSubmit={(e) => {
        e.preventDefault();
        if (!isStreaming && value.trim()) onSend();
      }}
      className="w-full max-w-[740px] rounded-glass pb-2.5 pl-[18px] pr-3 pt-3 transition-shadow duration-300 focus-within:shadow-[var(--glass-shadow),var(--glass-spec),0_0_0_4px_hsl(var(--primary)/0.12)]"
    >
      <textarea
        rows={1}
        value={value}
        disabled={disabled || isStreaming}
        placeholder="Ask Atlas about revenue, campaigns, accounts…"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            if (!isStreaming && value.trim()) onSend();
          }
        }}
        className="max-h-40 min-h-[26px] w-full resize-none bg-transparent text-answer text-ink outline-none placeholder:text-muted-2 disabled:opacity-60 [field-sizing:content]"
      />
      <div className="mt-1.5 flex items-center gap-1.5">
        <span className="text-caption text-muted-2">Answers come from governed metrics, with provenance on every number.</span>
        <span
          aria-live="polite"
          className={cn('ml-auto font-mono text-caption text-muted-foreground transition-opacity', isStreaming ? 'opacity-100' : 'opacity-0')}
        >
          {isStreaming ? `${elapsed}s` : ''}
        </span>
        <Button
          type={isStreaming ? 'button' : 'submit'}
          variant="send"
          size="send"
          data-streaming={isStreaming}
          aria-label={isStreaming ? 'Stop generating' : 'Send'}
          disabled={!isStreaming && (!value.trim() || disabled)}
          onClick={isStreaming ? onStop : undefined}
          className="relative"
        >
          <span aria-hidden className={cn('absolute -inset-1 rounded-full border-2 border-transparent border-t-primary transition-opacity', isStreaming ? 'animate-spin opacity-100' : 'opacity-0')} />
          <ArrowUp className={cn('transition-opacity duration-200', isStreaming && 'opacity-0')} />
          <span aria-hidden className={cn('absolute h-[11px] w-[11px] rounded-[3px] bg-white transition-transform duration-300 ease-out', isStreaming ? 'scale-100' : 'scale-0')} />
        </Button>
      </div>
    </Glass>
  );
}
```

- [ ] **Step 4: Run + commit**

Run: `corepack pnpm vitest run src/features/chat/composer.test.tsx` → PASS

```bash
git add src/features/chat/composer.tsx src/features/chat/composer.test.tsx
git commit -m "feat(chat): glass composer with send-stop morph and timer"
```

---

### Task 7: Notices + provenance chips with popover

**Files:** Create `src/features/chat/notice.tsx` (+ test); Rewrite `src/features/chat/provenance-chips.tsx`; Modify `src/features/chat/provenance-chips.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// src/features/chat/notice.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Notice } from './notice';

describe('Notice', () => {
  it('blocked states the reason plainly', () => {
    render(<Notice kind="blocked" message="Daily message limit reached." />);
    expect(screen.getByRole('status')).toHaveTextContent('Daily message limit reached.');
  });

  it('error offers retry', async () => {
    const onRetry = vi.fn();
    render(<Notice kind="error" message="Connection lost." onRetry={onRetry} />);
    await userEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('stale warning names the source and age', () => {
    render(<Notice kind="stale" message="DeepSales last synced 26h ago" />);
    expect(screen.getByRole('status')).toHaveTextContent('DeepSales last synced 26h ago');
    expect(screen.getByRole('status')).toHaveTextContent('Recent changes may be missing');
  });
});
```

Add to `provenance-chips.test.tsx` (keep the existing 5 cases; their text assertions still hold):

```tsx
  it('opens a glass definition popover from the chip', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    render(<ProvenanceChips provenance={[base]} />);
    await userEvent.click(screen.getByRole('button', { name: /Total revenue/ }));
    expect(await screen.findByText('revenue_total')).toBeInTheDocument();
  });

  it('marks stale sources amber', () => {
    render(<ProvenanceChips provenance={[{ ...base, freshness: '2020-01-01T00:00:00Z' }]} />);
    expect(screen.getByRole('button', { name: /Total revenue/ })).toHaveAttribute('data-stale', 'true');
  });
```

Leave the existing `'renders metric name, source, and freshness'` case unchanged: `freshnessLabel` passes unparseable values like `'2h ago'` through as-is, so it still holds.

- [ ] **Step 2: Run to verify failure** → FAIL

- [ ] **Step 3: Implement `notice.tsx`**

```tsx
// src/features/chat/notice.tsx
import { AlertCircle, Clock3, ShieldAlert } from 'lucide-react';
import { Button, cn } from '@/ui';

interface NoticeProps {
  kind: 'blocked' | 'error' | 'stale';
  message: string;
  onRetry?: () => void;
}

const ICON = { blocked: ShieldAlert, error: AlertCircle, stale: Clock3 } as const;

/** DESIGN.md › notice-denied / notice-warning: state the fact plus a next step. Never hide it. */
export function Notice({ kind, message, onRetry }: NoticeProps) {
  const Icon = ICON[kind];
  return (
    <div
      role="status"
      className={cn(
        'my-3 flex items-start gap-3 rounded-card px-4 py-3.5',
        kind === 'stale'
          ? 'bg-warning/10 shadow-[0_0_0_1px_hsl(var(--warning)/0.25)]'
          : 'bg-card shadow-[0_0_0_1px_hsl(var(--border))]',
      )}
    >
      <span className={cn('grid h-[30px] w-[30px] shrink-0 place-items-center rounded-full', kind === 'stale' ? 'bg-warning/20 text-warning' : 'bg-foreground/5 text-ink')}>
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1 text-sm text-body">
        <p className="font-medium text-ink">{message}</p>
        {kind === 'stale' && <p>Recent changes may be missing from these numbers.</p>}
      </div>
      {kind === 'error' && onRetry && (
        <Button variant="pill" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Rewrite `provenance-chips.tsx`**

```tsx
import { Database } from 'lucide-react';
import { cn, Popover, PopoverContent, PopoverTrigger } from '@/ui';
import type { Provenance } from '@/api/chat';
import { formatDateTime } from '@/lib/utils';
import { freshnessLabel, isStale } from '@/lib/freshness';

interface ProvenanceChipsProps {
  provenance: Provenance[];
}

/** Every number traces to one of these (guardrail #2). Built from the tool audit,
 * never LLM output. Click a chip to see the governed definition (glass popover). */
export function ProvenanceChips({ provenance }: ProvenanceChipsProps) {
  const chips = Array.from(new Map(provenance.map((p) => [`${p.metric_id ?? p.tool}::${p.source}`, p])).values());
  if (chips.length === 0) return null;

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5" aria-label="Data provenance">
      {chips.map((p) => {
        const stale = isStale(p.freshness);
        return (
          <Popover key={`${p.metric_id ?? p.tool}::${p.source}`}>
            <PopoverTrigger
              data-stale={stale}
              className={cn(
                'inline-flex max-w-full items-center gap-1.5 rounded-full border border-border/60 bg-card-2 py-[3px] pl-2 pr-2.5 text-caption text-muted-foreground transition-colors duration-200 hover:text-ink active:scale-[.97]',
                stale && 'border-warning/40 text-warning',
              )}
            >
              <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', stale ? 'bg-warning' : 'bg-positive')} />
              <span className="truncate font-medium text-ink/90">{p.metric_name ?? p.tool}</span>
              <span className="text-muted-2">·</span>
              <span className="truncate">{p.source}</span>
              {p.freshness && (
                <>
                  <span className="text-muted-2">·</span>
                  <span className="shrink-0">{freshnessLabel(p.freshness)}</span>
                </>
              )}
              <Database className="sr-only" aria-hidden />
            </PopoverTrigger>
            <PopoverContent className="space-y-1">
              <p className="font-serif text-section text-ink">{p.metric_name ?? p.tool}</p>
              {p.metric_id && (
                <p>
                  metric <code className="font-mono text-[11.5px]">{p.metric_id}</code>
                </p>
              )}
              <p>
                source <span className="text-ink">{p.source}</span> (read-only) · tool{' '}
                <code className="font-mono text-[11.5px]">{p.tool}</code>
              </p>
              {p.freshness && <p>data as of {freshnessLabel(p.freshness)}</p>}
              <p className="text-muted-foreground">executed {formatDateTime(p.executed_at)}</p>
            </PopoverContent>
          </Popover>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 5: Run + commit**

Run: `corepack pnpm vitest run src/features/chat/notice.test.tsx src/features/chat/provenance-chips.test.tsx` → PASS

```bash
git add src/features/chat/notice.tsx src/features/chat/notice.test.tsx src/features/chat/provenance-chips.tsx src/features/chat/provenance-chips.test.tsx
git commit -m "feat(chat): notices and provenance definition popover with staleness"
```

---

### Task 8: Message actions (copy + feedback morphs) and stick-to-bottom

**Files:** Create `message-actions.tsx` (+ test), `use-stick-to-bottom.ts` (+ test); Delete `message-feedback.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// src/features/chat/message-actions.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MessageActions } from './message-actions';

const setFeedback = vi.hoisted(() => vi.fn());
vi.mock('@/api/chat', () => ({ setMessageFeedback: setFeedback }));

describe('MessageActions', () => {
  it('copies the answer and morphs copy → check in place', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<MessageActions messageId="m1" text="Revenue was 42" initialRating={null} />);
    await userEvent.click(screen.getByRole('button', { name: 'Copy answer' }));
    expect(writeText).toHaveBeenCalledWith('Revenue was 42');
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument();
  });

  it('thumbs down reveals categories and sends feedback', async () => {
    render(<MessageActions messageId="m1" text="x" initialRating={null} />);
    await userEvent.click(screen.getByRole('button', { name: 'Bad answer' }));
    expect(setFeedback).toHaveBeenCalledWith('m1', { rating: 'down' });
    await userEvent.click(screen.getByRole('button', { name: 'Inaccurate' }));
    expect(setFeedback).toHaveBeenCalledWith('m1', { rating: 'down', category: 'inaccurate' });
  });
});
```

```ts
// src/features/chat/use-stick-to-bottom.test.ts
import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useStickToBottom } from './use-stick-to-bottom';

function scroller(scrollTop: number, scrollHeight = 2000, clientHeight = 600) {
  const el = document.createElement('div');
  Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => scrollHeight });
  Object.defineProperty(el, 'clientHeight', { configurable: true, get: () => clientHeight });
  el.scrollTop = scrollTop;
  return el;
}

describe('useStickToBottom', () => {
  it('follows new content while the reader is near the bottom', () => {
    const el = scroller(1300); // 100px from bottom
    const ref = { current: el };
    const { rerender } = renderHook(({ dep }) => useStickToBottom(ref, [dep]), { initialProps: { dep: 1 } });
    el.dispatchEvent(new Event('scroll'));
    rerender({ dep: 2 });
    expect(el.scrollTop).toBe(2000);
  });

  it('does not yank the reader who scrolled up', () => {
    const el = scroller(200); // far from bottom
    const ref = { current: el };
    const { rerender } = renderHook(({ dep }) => useStickToBottom(ref, [dep]), { initialProps: { dep: 1 } });
    el.dispatchEvent(new Event('scroll'));
    rerender({ dep: 2 });
    expect(el.scrollTop).toBe(200);
  });
});
```

- [ ] **Step 2: Run to verify failure** → FAIL

- [ ] **Step 3: Implement**

```ts
// src/features/chat/use-stick-to-bottom.ts
import { useEffect, useRef, type DependencyList, type RefObject } from 'react';

const NEAR_BOTTOM_PX = 240;

/** DESIGN.md › Streaming: auto-scroll only while the reader is within 240px of
 * the bottom; scrolling up pauses it. */
export function useStickToBottom(ref: RefObject<HTMLElement | null>, deps: DependencyList) {
  const nearBottom = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => {
      nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, [ref]);

  useEffect(() => {
    const el = ref.current;
    if (el && nearBottom.current) el.scrollTop = el.scrollHeight;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
```

```tsx
// src/features/chat/message-actions.tsx
import { useState } from 'react';
import { Check, Copy, ThumbsDown, ThumbsUp } from 'lucide-react';
import { setMessageFeedback, type FeedbackCategory } from '@/api/chat';
import { Button, cn } from '@/ui';

const CATEGORIES: { key: FeedbackCategory; label: string }[] = [
  { key: 'inaccurate', label: 'Inaccurate' },
  { key: 'incomplete', label: 'Incomplete' },
  { key: 'not_relevant', label: 'Not relevant' },
];

interface MessageActionsProps {
  messageId: string;
  text: string;
  initialRating: 'up' | 'down' | null;
}

const iconBtn =
  'grid h-8 w-8 place-items-center rounded-full text-muted-foreground transition-[color,background-color,transform] duration-200 hover:bg-foreground/5 hover:text-ink active:scale-90';

/** In-place feedback (DESIGN.md › Feedback vocabulary): icons morph where you
 * clicked; no toast for things the user can already see change. */
export function MessageActions({ messageId, text, initialRating }: MessageActionsProps) {
  const [copied, setCopied] = useState(false);
  const [rating, setRating] = useState(initialRating);
  const [category, setCategory] = useState<FeedbackCategory | null>(null);

  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const rate = (r: 'up' | 'down') => {
    if (rating === r) return;
    setRating(r);
    setCategory(null);
    void setMessageFeedback(messageId, { rating: r });
  };

  return (
    <div className="mt-1">
      <div className="flex gap-0.5">
        <button type="button" aria-label={copied ? 'Copied' : 'Copy answer'} onClick={() => void copy()} className={iconBtn}>
          <span className="relative grid place-items-center">
            <Copy className={cn('h-3.5 w-3.5 transition-all duration-300 ease-out', copied && 'scale-50 opacity-0 blur-[3px]')} />
            <Check className={cn('absolute h-3.5 w-3.5 text-positive transition-all duration-300 ease-out', !copied && 'scale-50 opacity-0 blur-[3px]')} />
          </span>
        </button>
        <button type="button" aria-label="Good answer" aria-pressed={rating === 'up'} onClick={() => rate('up')} className={cn(iconBtn, rating === 'up' && 'text-primary-text')}>
          <ThumbsUp className={cn('h-3.5 w-3.5', rating === 'up' && 'fill-current')} />
        </button>
        <button type="button" aria-label="Bad answer" aria-pressed={rating === 'down'} onClick={() => rate('down')} className={cn(iconBtn, rating === 'down' && 'text-negative')}>
          <ThumbsDown className={cn('h-3.5 w-3.5', rating === 'down' && 'fill-current')} />
        </button>
      </div>
      {rating === 'down' && (
        <div className="mt-1 flex flex-wrap gap-1.5">
          {CATEGORIES.map((c) => (
            <Button
              key={c.key}
              variant="pill"
              size="sm"
              data-selected={category === c.key}
              aria-pressed={category === c.key}
              onClick={() => {
                setCategory(c.key);
                void setMessageFeedback(messageId, { rating: 'down', category: c.key });
              }}
              className="h-7 text-caption"
            >
              {c.label}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
```

```bash
git rm src/features/chat/message-feedback.tsx
```

- [ ] **Step 4: Run + commit**

Run: `corepack pnpm vitest run src/features/chat/message-actions.test.tsx src/features/chat/use-stick-to-bottom.test.ts` → PASS

```bash
git add -A src/features/chat
git commit -m "feat(chat): in-place copy/feedback morphs and stick-to-bottom"
```

---

### Task 9: Presets + chat panel composition

**Files:** Rewrite `src/features/chat/chat-suggestions.ts`, `src/features/chat/chat-panel.tsx`; Create `src/features/chat/chat-panel.test.tsx`

- [ ] **Step 1: Rewrite `chat-suggestions.ts`**

```ts
// Preset analyses for the empty chat (Higgsfield-style gallery). Static and
// curated; each preset sends its question.
import type { PresetPreview } from '@/ui';

export interface ChatPreset {
  title: string;
  description: string;
  preview: PresetPreview;
  question: string;
}

export const CHAT_PRESETS: ChatPreset[] = [
  { title: 'Revenue review', description: 'Last week, with drivers', preview: 'line', question: 'What was revenue last week?' },
  { title: 'Account health', description: 'Who is at risk', preview: 'bars', question: 'How many accounts are currently at risk?' },
  { title: 'CSM workload', description: 'Open tasks by CSM', preview: 'bars', question: 'How are open tasks distributed across CSMs?' },
  { title: 'Checkout funnel', description: 'Where users drop off', preview: 'funnel', question: 'Where do users drop off in checkout?' },
];
```

- [ ] **Step 2: Write the failing panel test**

```tsx
// src/features/chat/chat-panel.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { ChatPanel } from './chat-panel';

const send = vi.hoisted(() => vi.fn());
vi.mock('./use-chat-turn', () => ({
  useChatTurn: () => ({ draft: null, isStreaming: false, send, abort: vi.fn(), notice: null, lastTurn: null }),
}));
vi.mock('@/api/hooks/use-chat-sessions', () => ({ useChatMessages: () => ({ data: [] }) }));

function renderPanel() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <ChatPanel sessionId={null} ensureSession={async () => 's1'} />
    </QueryClientProvider>,
  );
}

describe('ChatPanel', () => {
  it('empty state: serif greeting, preset gallery, centered composer', async () => {
    renderPanel();
    expect(screen.getByRole('heading', { name: 'What would you like to know?' })).toHaveClass('font-serif');
    await userEvent.click(screen.getByRole('button', { name: /Revenue review/ }));
    expect(send).toHaveBeenCalledWith('What was revenue last week?');
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run to verify failure** → FAIL

- [ ] **Step 4: Rewrite `chat-panel.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import { PresetCard, springDefault } from '@/ui';
import { useChatMessages } from '@/api/hooks/use-chat-sessions';
import type { Provenance } from '@/api/chat';
import { useChatTurn } from './use-chat-turn';
import { MarkdownMessage } from './markdown-message';
import { ProvenanceChips } from './provenance-chips';
import { MessageActions } from './message-actions';
import { StepsBlock } from './steps-block';
import { Composer } from './composer';
import { Notice } from './notice';
import { CHAT_PRESETS } from './chat-suggestions';
import { stepsFromProvenance } from './steps';
import { freshnessLabel, isStale } from '@/lib/freshness';
import { useStickToBottom } from './use-stick-to-bottom';

interface ChatPanelProps {
  sessionId: string | null;
  ensureSession?: () => Promise<string>;
}

function StaleWarning({ provenance }: { provenance: Provenance[] }) {
  const stale = provenance.find((p) => isStale(p.freshness));
  if (!stale) return null;
  return <Notice kind="stale" message={`${stale.source} last synced ${freshnessLabel(stale.freshness)}`} />;
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="mb-5 mt-1.5 flex justify-end">
      <div className="max-w-[80%] whitespace-pre-wrap rounded-[20px] rounded-br-md border border-border/60 bg-card-2 px-[15px] py-2.5 text-body">
        {text}
      </div>
    </div>
  );
}

export function ChatPanel({ sessionId, ensureSession }: ChatPanelProps) {
  const { data: messages = [] } = useChatMessages(sessionId);
  const { draft, isStreaming, send, abort, notice, lastTurn } = useChatTurn(sessionId, ensureSession);
  const [input, setInput] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => () => abort(), [abort]);
  useStickToBottom(scrollRef, [messages.length, draft?.assistantText, draft?.steps.length, notice]);

  const canSend = !!(sessionId || ensureSession);
  const sendText = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || isStreaming || !canSend) return;
    setInput('');
    void send(trimmed);
  };
  const isEmpty = messages.length === 0 && !draft && !notice;

  const composer = (
    <motion.div layoutId="atlas-composer" transition={springDefault} className="flex w-full justify-center">
      <Composer
        value={input}
        onChange={setInput}
        onSend={() => sendText(input)}
        onStop={abort}
        isStreaming={isStreaming}
        disabled={!canSend}
        startedAt={draft?.startedAt}
      />
    </motion.div>
  );

  return (
    <div className="absolute inset-0">
      <div ref={scrollRef} className="absolute inset-0 overflow-y-auto">
        {isEmpty ? (
          <div className="mx-auto max-w-[740px] px-6 pt-[20vh] text-center">
            <h2 className="font-serif text-display text-ink">What would you like to know?</h2>
            <p className="mt-1.5 text-muted-foreground">
              Ask about revenue, campaigns, accounts or funnels. Every number comes from a governed metric.
            </p>
            <div className="mt-8">{composer}</div>
            <div className="mt-8 grid grid-cols-2 gap-3 text-left md:grid-cols-4">
              {CHAT_PRESETS.map((p) => (
                <PresetCard key={p.title} title={p.title} description={p.description} preview={p.preview} compact onSelect={() => sendText(p.question)} />
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-[740px] px-6 pb-[190px] pt-[84px]">
            {messages.map((m) =>
              m.role === 'user' ? (
                <UserBubble key={m.id} text={m.content} />
              ) : (
                <div key={m.id} className="mb-6">
                  <StepsBlock
                    steps={lastTurn?.messageId === m.id ? lastTurn.steps : stepsFromProvenance(m.provenance ?? [])}
                    durationMs={lastTurn?.messageId === m.id ? lastTurn.durationMs : undefined}
                  />
                  <StaleWarning provenance={m.provenance ?? []} />
                  <MarkdownMessage text={m.content} />
                  {m.provenance && m.provenance.length > 0 && <ProvenanceChips provenance={m.provenance} />}
                  <MessageActions messageId={m.id} text={m.content} initialRating={m.feedback_rating ?? null} />
                </div>
              ),
            )}

            {draft && (
              <>
                {!messages.some((m) => m.role === 'user' && m.content === draft.userText) && <UserBubble text={draft.userText} />}
                <StepsBlock steps={draft.steps} live={draft.phase !== null} />
                {draft.phase === 'thinking' && draft.steps.length === 0 && (
                  <p className="mb-3 text-label text-muted-foreground">Thinking…</p>
                )}
                {draft.assistantText && <MarkdownMessage text={draft.assistantText} streaming={draft.phase === 'streaming'} />}
                {draft.provenance && draft.provenance.length > 0 && <ProvenanceChips provenance={draft.provenance} />}
              </>
            )}

            {notice && (
              <Notice kind={notice.kind} message={notice.message} onRetry={notice.kind === 'error' ? () => sendText(notice.retryText) : undefined} />
            )}
          </div>
        )}
      </div>

      {!isEmpty && (
        <>
          <div aria-hidden className="scroll-edge-bottom pointer-events-none absolute inset-x-0 bottom-0 z-[5] h-[130px]" />
          <div className="absolute inset-x-0 bottom-4 z-10 px-6">{composer}</div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Run the full feature suite + lint + typecheck**

Run: `corepack pnpm test && corepack pnpm lint && corepack pnpm typecheck`
Expected: PASS. Fix `use-chat-turn.test.tsx` only where it referenced removed exports.

- [ ] **Step 6: Visual check (required for UI tracks)**

Run the app with the backend. Check against `docs/design/reference/atlas-hybrid-glass.html` Mode ①, cases 2, 3 and 7:
- **Empty state:** serif greeting, centered glass composer, preset cards preview on hover. Send a preset and the composer glides to the bottom.
- **Streaming:** words blur in, with no reflow of earlier text. The steps block shows mono tool ids live, then folds to "Worked for Ns · N steps".
- **Composer:** send⇄stop morph with the ring, and the timer counts.
- **Provenance:** chip popover opens from the chip. A stale source shows the amber notice and chip.
- **Blocked and error:** notices stay after the stream ends, and Retry works.
- **Settings:** dark, reduced-motion (no blur-in, no glide) and reduced-transparency (solid composer).

- [ ] **Step 7: Commit**

```bash
git add -A src/features/chat
git commit -m "feat(chat): Hybrid Glass chat panel composition"
```

---

### Task 10: `/ask?q=` prefill (shared entry point for dashboard, catalog, ⌘K)

Other tracks start a question by navigating to `/ask?q=<question>`. The chat page sends it once, then removes
the parameter so a refresh doesn't resend it.

**Files:** Modify `src/features/chat/index.tsx`; Create `src/features/chat/chat-page.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// src/features/chat/chat-page.test.tsx
import { render, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import ChatPage from './index';

const panelProps = vi.hoisted(() => vi.fn());
vi.mock('./chat-panel', () => ({
  ChatPanel: (props: { initialQuestion?: string | null }) => {
    panelProps(props);
    return null;
  },
}));
vi.mock('@/api/hooks/use-chat-sessions', () => ({
  useChatSessions: () => ({ data: [] }),
  useCreateChatSession: () => ({ mutateAsync: vi.fn() }),
}));

let search = '';
function Spy() {
  search = useLocation().search;
  return null;
}

describe('ChatPage ?q= prefill', () => {
  it('hands the question to the panel once and clears the param', async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/ask?q=What%20was%20revenue%3F']}>
          <Routes>
            <Route path="/ask/:sessionId?" element={<><ChatPage /><Spy /></>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(search).toBe(''));
    expect(panelProps).toHaveBeenCalledWith(expect.objectContaining({ initialQuestion: 'What was revenue?' }));
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `corepack pnpm vitest run src/features/chat/chat-page.test.tsx` → FAIL (`initialQuestion` never passed)

- [ ] **Step 3: Implement**

In `index.tsx`: read the param once and clear it.
```tsx
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
// inside ChatPage:
  const [params, setParams] = useSearchParams();
  const [initialQuestion] = useState(() => params.get('q'));
  useEffect(() => {
    if (params.has('q')) setParams({}, { replace: true });
  }, [params, setParams]);
  // ...
  <ChatPanel sessionId={sessionId} ensureSession={sessionId ? undefined : ensureSession} initialQuestion={initialQuestion} />
```
(add `useEffect` to the react import.)

In `chat-panel.tsx`: add `initialQuestion?: string | null` to `ChatPanelProps` and send it exactly once:
```tsx
  const sentInitial = useRef(false);
  useEffect(() => {
    if (initialQuestion && !sentInitial.current && canSend) {
      sentInitial.current = true;
      void send(initialQuestion);
    }
  }, [initialQuestion, canSend, send]);
```

- [ ] **Step 4: Run tests + commit**

Run: `corepack pnpm test` → PASS

```bash
git add src/features/chat
git commit -m "feat(chat): /ask?q= prefill entry point"
```


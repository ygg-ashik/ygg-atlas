# Hybrid Glass Track A: Frontend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Follow the `engineering-standards` skill before writing code and the `production-code-review` skill before calling the track done. Gate: `make check` from the repo root (run `make format` first: the code below predates prettier/ruff formatting).

**Goal:** Put DESIGN.md tokens, fonts, glass/motion primitives, and the floating glass shell with URL-based chat routing into the frontend so every other track builds on them.

**Architecture:** Tokens live as CSS variables in `src/index.css` (HSL triplets, shadcn names remapped + DESIGN.md names added), mapped in `tailwind.config.js`. Presentational primitives (`Glass`, `Toolbar`, `Popover`, `Toaster`, motion presets, restyled `Button`) live in `src/ui` and are exported from `src/ui/index.ts`. The layout feature renders a floating glass sidebar with nav and a threads slot. `App.tsx` composes the chat feature's new `ChatThreadList` into that slot and routes `/ask/:sessionId?`.

**Tech Stack:** React 19, Vite, Tailwind 3, Radix, `motion` 14, `sonner`, `@radix-ui/react-popover`, `@fontsource-variable/*`, Vitest + Testing Library (happy-dom).

**Branch/worktree:** `feature/hybrid-glass-a` · All commands run from `frontend/` with `corepack pnpm`.

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `src/index.css` | Rewrite | Tokens (light/dark), ambient wash, glass/scroll-edge/specular utilities, a11y media queries |
| `tailwind.config.js` | Rewrite | Map tokens → Tailwind colors, fonts, type scale, radii, easing, keyframes; scan streamdown |
| `src/main.tsx` | Modify | Import self-hosted fonts + streamdown styles |
| `src/ui/tokens.test.ts` | Create | Contract test: required tokens exist in light + dark |
| `src/ui/motion.ts` (+ test) | Create | Motion presets (springs, durations, materialize, reduced-motion helper) |
| `src/ui/glass.tsx` (+ test) | Create | `Glass` surface with variants + pointer-following specular |
| `src/ui/toolbar.tsx` (+ test) | Create | Floating glass page toolbar + scroll-edge blur |
| `src/ui/button.tsx` (+ test) | Modify | DESIGN.md button variants (pill, send, press scale) |
| `src/ui/popover.tsx` (+ test) | Create | Radix popover with glass materialize |
| `src/ui/toaster.tsx` | Create | Sonner toaster styled as glass |
| `src/ui/index.ts` | Modify | Export new primitives |
| `eslint.config.js` | Modify | Ban hex color literals in `src/features/**` |
| `src/features/auth/login.tsx` | Modify | Scoped eslint-disable for official Google mark colors |
| `src/features/layout/shell.tsx` (+ test) | Rewrite | Floating glass sidebar: brand, nav, threads slot, theme + user menu |
| `src/features/layout/index.ts` | Modify | Export `Shell`, `type NavItem` |
| `src/features/chat/chat-thread-list.tsx` (+ test) | Create | Session list (moved out of `index.tsx`), URL-driven |
| `src/features/chat/index.tsx` | Rewrite | `ChatPage` reads `:sessionId` from the URL; exports `ChatThreadList` |
| `src/features/chat/chat-panel.tsx` | Modify | Top padding for the floating toolbar only (Track B restyles) |
| `src/App.tsx` | Rewrite | Layout route with Shell + Outlet, `/ask/:sessionId?`, Toaster |
| `src/ui/preset-card.tsx` (+ test) | Create | Preset gallery card with hover-play preview (Task 12) |
| `src/lib/freshness.ts` (+ test) | Create | Shared provenance freshness helpers (Task 13) |

---

### Task 0: Restructure the chat feature (ARCHITECTURE.md §3.2)

The chat feature is past ~8 files and will grow. Move it into `components/` and `hooks/` **before** any
other change, as a pure move (no behavior change), so every later task and track uses the final layout.

**Files:** Move within `src/features/chat/`

- [ ] **Step 1: Move files**

```bash
cd src/features/chat
mkdir -p components hooks
git mv chat-panel.tsx markdown-message.tsx message-feedback.tsx provenance-chips.tsx provenance-chips.test.tsx components/
git mv use-chat-turn.ts use-chat-turn.test.tsx hooks/
```
`index.tsx`, `chat-suggestions.ts`, `markdown-stream.ts` (+ test) stay at the root.

- [ ] **Step 2: Fix relative imports**

Update every moved file's imports (`./use-chat-turn` → `../hooks/use-chat-turn`, `./chat-suggestions` →
`../chat-suggestions`, `./markdown-stream` → `../markdown-stream`, `./chat-panel` → `./components/chat-panel`
in `index.tsx`, and so on). If the standards change already split `chat-panel.tsx` into several
components inside one file, extract each into its own file under `components/` now (`empty-state.tsx`,
`stored-message.tsx`, `draft-view.tsx`, `composer.tsx`), with no behavior change.

- [ ] **Step 3: Gate + commit**

Run: `make check-frontend` → green (all existing tests still pass unchanged).

```bash
git add -A src/features/chat
git commit -m "refactor(chat): components/ and hooks/ layout (ARCHITECTURE.md §3.2)"
```

All later tasks in this plan (Task 8: `chat-thread-list` → `components/`; Task 9: `index.tsx` imports
`./components/chat-panel`) use this layout.

---

### Task 1: Design tokens in CSS + Tailwind

**Files:**
- Create: `src/ui/tokens.test.ts`
- Modify: `src/index.css` (full rewrite), `tailwind.config.js` (full rewrite)

- [ ] **Step 1: Write the failing token contract test**

```ts
// src/ui/tokens.test.ts
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const css = readFileSync(fileURLToPath(new URL('../index.css', import.meta.url)), 'utf8');

function block(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  return match?.[1] ?? '';
}

const LIGHT = [
  'background', 'foreground', 'card', 'card-foreground', 'card-2', 'popover', 'popover-foreground',
  'primary', 'primary-foreground', 'primary-text', 'secondary', 'secondary-foreground', 'muted',
  'muted-foreground', 'muted-2', 'accent', 'accent-foreground', 'destructive',
  'destructive-foreground', 'border', 'input', 'ring', 'canvas', 'surface', 'ink', 'body',
  'positive', 'negative', 'warning', 'glass', 'glass-heavy', 'glass-edge', 'glass-shadow',
  'glass-spec', 'wash',
];

describe('design tokens (DESIGN.md contract)', () => {
  it.each(LIGHT)('light theme defines --%s', (name) => {
    expect(block(':root')).toContain(`--${name}:`);
  });

  it.each(LIGHT.filter((n) => n !== 'primary-foreground'))('dark theme defines --%s', (name) => {
    expect(block('.dark')).toContain(`--${name}:`);
  });

  it('primary is the DESIGN.md clay #b45536', () => {
    expect(block(':root')).toMatch(/--primary:\s*15 53\.8% 45\.9%;/);
  });

  it('dark text/links use primary-on-dark #d97a57', () => {
    expect(block('.dark')).toMatch(/--primary-text:\s*16 63\.1% 59\.6%;/);
  });

  it('falls back to solid surfaces for reduced transparency', () => {
    expect(css).toContain('@media (prefers-reduced-transparency: reduce)');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `corepack pnpm vitest run src/ui/tokens.test.ts`
Expected: FAIL (e.g. `light theme defines --card-2`, because the old palette lacks the new tokens).

- [ ] **Step 3: Rewrite `src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

/* Atlas Hybrid Glass tokens. Source of truth: /DESIGN.md.
   Colors are HSL triplets consumed as hsl(var(--x) / <alpha>) by tailwind.config.js.
   Glass values are full colors (rgba) consumed directly. */
@layer base {
  :root {
    /* DESIGN.md names */
    --canvas: 48 33.3% 97.1%;
    --surface: 39 38.9% 92.9%;
    --card-2: 38 40.7% 94.7%;
    --ink: 60 2.6% 7.6%;
    --body: 60 2.5% 23.3%;
    --muted-2: 45 5% 53.3%;
    --primary-text: 15 53.8% 45.9%;
    --positive: 135 33% 36.9%;
    --negative: 10 58.6% 44.5%;
    --warning: 36 71% 42%;

    /* shadcn names remapped onto DESIGN.md */
    --background: var(--canvas);
    --foreground: var(--ink);
    --card: 0 0% 100%;
    --card-foreground: var(--ink);
    --popover: 0 0% 100%;
    --popover-foreground: var(--ink);
    --primary: 15 53.8% 45.9%;
    --primary-foreground: 0 0% 100%;
    --secondary: var(--card-2);
    --secondary-foreground: var(--ink);
    --muted: var(--card-2);
    --muted-foreground: 45 3.8% 40.8%;
    --accent: 20 45% 93%;
    --accent-foreground: 15 53.8% 35%;
    --destructive: var(--negative);
    --destructive-foreground: 0 0% 100%;
    --border: 40 12% 88%;
    --input: 40 12% 84%;
    --ring: var(--primary);
    --radius: 0.75rem;

    /* glass material */
    --glass: rgba(255, 255, 255, 0.62);
    --glass-heavy: rgba(255, 255, 255, 0.72);
    --glass-edge: rgba(255, 255, 255, 0.8);
    --glass-shadow: 0 1px 1px rgba(20, 20, 19, 0.04), 0 10px 30px rgba(20, 20, 19, 0.08);
    --glass-spec: inset 0 1px 0 rgba(255, 255, 255, 0.95), inset 0 -1px 0 rgba(20, 20, 19, 0.03);
    --wash: radial-gradient(60% 50% at 15% -10%, rgba(232, 165, 90, 0.16), transparent 70%),
      radial-gradient(50% 40% at 95% 0%, rgba(180, 85, 54, 0.1), transparent 70%);
  }

  .dark {
    --canvas: 40 6.1% 9.6%;
    --surface: 36 8.2% 12%;
    --card-2: 40 7.5% 15.7%;
    --ink: 40 27.3% 93.5%;
    --body: 40 12.8% 81.6%;
    --muted-2: 42 4.2% 47.1%;
    --primary-text: 16 63.1% 59.6%;
    --positive: 134 36.5% 62.4%;
    --negative: 13 67.9% 67.1%;
    --warning: 38 70.8% 58.4%;

    --background: var(--canvas);
    --foreground: var(--ink);
    --card: 36 7.2% 13.5%;
    --card-foreground: var(--ink);
    --popover: 36 7.2% 13.5%;
    --popover-foreground: var(--ink);
    --primary: 15 53.8% 45.9%;
    --secondary: var(--card-2);
    --secondary-foreground: var(--ink);
    --muted: var(--card-2);
    --muted-foreground: 42 5% 60.8%;
    --accent: 15 25% 20%;
    --accent-foreground: 16 63% 75%;
    --destructive: var(--negative);
    --destructive-foreground: 0 0% 100%;
    --border: 40 5% 20%;
    --input: 40 5% 24%;
    --ring: var(--primary-text);

    --glass: rgba(40, 38, 34, 0.55);
    --glass-heavy: rgba(36, 35, 32, 0.7);
    --glass-edge: rgba(255, 255, 255, 0.1);
    --glass-shadow: 0 1px 1px rgba(0, 0, 0, 0.3), 0 12px 36px rgba(0, 0, 0, 0.45);
    --glass-spec: inset 0 1px 0 rgba(255, 255, 255, 0.12), inset 0 -1px 0 rgba(0, 0, 0, 0.2);
    --wash: radial-gradient(60% 50% at 15% -10%, rgba(232, 165, 90, 0.09), transparent 70%),
      radial-gradient(50% 40% at 95% 0%, rgba(217, 122, 87, 0.07), transparent 70%);
  }

  * {
    @apply border-border;
  }
  html,
  body,
  #root {
    height: 100%;
  }
  body {
    @apply bg-background font-sans text-foreground antialiased;
    background-image: var(--wash);
    transition:
      background-color 450ms cubic-bezier(0.22, 1, 0.36, 1),
      color 450ms cubic-bezier(0.22, 1, 0.36, 1);
  }
  code,
  pre,
  kbd {
    @apply font-mono;
  }
}

@layer components {
  /* Floating functional layer only (DESIGN.md › Elevation & Depth). Never under data. */
  .glass {
    position: relative;
    background: var(--glass);
    -webkit-backdrop-filter: saturate(180%) blur(22px);
    backdrop-filter: saturate(180%) blur(22px);
    border: 1px solid var(--glass-edge);
    box-shadow: var(--glass-shadow), var(--glass-spec);
  }
  .glass-heavy {
    background: var(--glass-heavy);
  }
  .glass-specular::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    pointer-events: none;
    background: radial-gradient(
      180px 100px at var(--spec-x, 50%) var(--spec-y, -30%),
      rgba(255, 255, 255, 0.55),
      transparent 65%
    );
    mix-blend-mode: soft-light;
  }
  /* Scroll-edge effect: soft blur where content meets floating chrome (no hard dividers). */
  .scroll-edge-top,
  .scroll-edge-bottom {
    -webkit-backdrop-filter: blur(6px);
    backdrop-filter: blur(6px);
  }
  .scroll-edge-top {
    -webkit-mask-image: linear-gradient(#000 30%, transparent);
    mask-image: linear-gradient(#000 30%, transparent);
  }
  .scroll-edge-bottom {
    -webkit-mask-image: linear-gradient(to top, #000 35%, transparent);
    mask-image: linear-gradient(to top, #000 35%, transparent);
  }
  .tabular {
    font-variant-numeric: tabular-nums;
  }
}

@media (prefers-reduced-transparency: reduce) {
  .glass,
  .glass-heavy {
    background: hsl(var(--card));
    -webkit-backdrop-filter: none;
    backdrop-filter: none;
  }
  .glass-specular::after,
  .scroll-edge-top,
  .scroll-edge-bottom {
    display: none;
  }
}

@media (prefers-contrast: more) {
  .glass,
  .glass-heavy {
    background: hsl(var(--card));
    border-color: hsl(var(--ink));
  }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 1ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 1ms !important;
  }
}
```

- [ ] **Step 4: Rewrite `tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
import animate from 'tailwindcss-animate';

// Token → Tailwind color with opacity-modifier support (bg-primary/15 etc.).
const v = (name) => `hsl(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}', './node_modules/streamdown/dist/*.js'],
  theme: {
    extend: {
      colors: {
        border: v('border'),
        input: v('input'),
        ring: v('ring'),
        background: v('background'),
        foreground: v('foreground'),
        primary: { DEFAULT: v('primary'), foreground: v('primary-foreground'), text: v('primary-text') },
        secondary: { DEFAULT: v('secondary'), foreground: v('secondary-foreground') },
        destructive: { DEFAULT: v('destructive'), foreground: v('destructive-foreground') },
        muted: { DEFAULT: v('muted'), foreground: v('muted-foreground') },
        accent: { DEFAULT: v('accent'), foreground: v('accent-foreground') },
        popover: { DEFAULT: v('popover'), foreground: v('popover-foreground') },
        card: { DEFAULT: v('card'), foreground: v('card-foreground'), 2: v('card-2') },
        canvas: v('canvas'),
        surface: v('surface'),
        ink: v('ink'),
        body: v('body'),
        'muted-2': v('muted-2'),
        positive: v('positive'),
        negative: v('negative'),
        warning: v('warning'),
        glass: { DEFAULT: 'var(--glass)', heavy: 'var(--glass-heavy)', edge: 'var(--glass-edge)' },
      },
      fontFamily: {
        sans: ['"Inter Variable"', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'],
        serif: ['"Source Serif 4 Variable"', 'Georgia', 'serif'],
        mono: ['"JetBrains Mono Variable"', 'ui-monospace', 'Menlo', 'monospace'],
      },
      fontSize: {
        display: ['32px', { lineHeight: '1.15', letterSpacing: '-0.01em' }],
        title: ['23px', { lineHeight: '1.25', letterSpacing: '-0.01em' }],
        section: ['19px', { lineHeight: '1.3', letterSpacing: '-0.005em' }],
        answer: ['15.5px', { lineHeight: '1.65' }],
        label: ['13px', { lineHeight: '1.4' }],
        caption: ['11.5px', { lineHeight: '1.4', letterSpacing: '0.005em' }],
        'metric-xl': ['32px', { lineHeight: '1.1', letterSpacing: '-0.03em' }],
        'metric-lg': ['27px', { lineHeight: '1.1', letterSpacing: '-0.025em' }],
      },
      borderRadius: {
        sm: '8px',
        md: '12px',
        lg: '16px',
        card: '18px',
        shell: '22px',
        feature: '24px',
        glass: '26px',
      },
      transitionTimingFunction: {
        out: 'cubic-bezier(.22,1,.36,1)',
        sheet: 'cubic-bezier(.32,.72,0,1)',
      },
      keyframes: {
        'materialize-in': {
          from: { opacity: '0', transform: 'scale(.94)', filter: 'blur(6px)' },
          to: { opacity: '1', transform: 'scale(1)', filter: 'blur(0)' },
        },
        'materialize-out': {
          from: { opacity: '1', transform: 'scale(1)', filter: 'blur(0)' },
          to: { opacity: '0', transform: 'scale(.96)', filter: 'blur(6px)' },
        },
        shimmer: { from: { backgroundPosition: '120% 0' }, to: { backgroundPosition: '-80% 0' } },
        'caret-pulse': { '50%': { transform: 'scale(.6)', opacity: '.5' } },
      },
      animation: {
        'materialize-in': 'materialize-in 320ms cubic-bezier(.22,1,.36,1) both',
        'materialize-out': 'materialize-out 220ms cubic-bezier(.22,1,.36,1) both',
        shimmer: 'shimmer 1.6s linear infinite',
        'caret-pulse': 'caret-pulse 1s ease-in-out infinite',
      },
    },
  },
  plugins: [animate],
};
```

- [ ] **Step 5: Run the token test**

Run: `corepack pnpm vitest run src/ui/tokens.test.ts`
Expected: PASS (all cases).

- [ ] **Step 6: Run the full suite + typecheck**

Run: `corepack pnpm test && corepack pnpm typecheck`
Expected: all tests pass (the remapped shadcn names keep existing components compiling).

- [ ] **Step 7: Commit**

```bash
git add src/index.css tailwind.config.js src/ui/tokens.test.ts
git commit -m "feat(ui): Atlas Hybrid Glass design tokens from DESIGN.md"
```

---

### Task 2: Self-hosted fonts + streamdown styles

**Files:** Modify `src/main.tsx`

- [ ] **Step 1: Import fonts and streamdown CSS**

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/inter';
import '@fontsource-variable/source-serif-4';
import '@fontsource-variable/jetbrains-mono';
import 'streamdown/styles.css';
import App from './App';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 2: Verify the build bundles the fonts**

Run: `corepack pnpm build && ls dist/assets | grep -E "inter|source-serif|jetbrains" | head`
Expected: `.woff2` files for all three families. No requests to fonts.googleapis.com (`grep -r googleapis dist` prints nothing).

- [ ] **Step 3: Commit**

```bash
git add src/main.tsx
git commit -m "feat(ui): self-host Inter, Source Serif 4, JetBrains Mono"
```

---

### Task 3: Motion presets

**Files:** Create `src/ui/motion.ts`, `src/ui/motion.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// src/ui/motion.test.ts
import { describe, expect, it } from 'vitest';
import { durations, materialize, springDefault, springMomentum, withReducedMotion } from './motion';

describe('motion presets (DESIGN.md › Motion)', () => {
  it('default spring is critically damped (no bounce)', () => {
    expect(springDefault).toMatchObject({ type: 'spring', bounce: 0, duration: 0.35 });
  });

  it('momentum spring has a small bounce', () => {
    expect(springMomentum).toMatchObject({ type: 'spring', bounce: 0.2 });
  });

  it('exposes the duration tokens in seconds', () => {
    expect(durations).toEqual({ press: 0.1, micro: 0.2, standard: 0.4, panel: 0.6 });
  });

  it('materialize animates opacity, scale and blur together', () => {
    expect(materialize.initial).toMatchObject({ opacity: 0, scale: 0.94, filter: 'blur(6px)' });
    expect(materialize.animate).toMatchObject({ opacity: 1, scale: 1, filter: 'blur(0px)' });
  });

  it('replaces any transition with a short cross-fade when motion is reduced', () => {
    expect(withReducedMotion(springDefault, true)).toEqual({ duration: 0.15, ease: 'linear' });
    expect(withReducedMotion(springDefault, false)).toBe(springDefault);
    expect(withReducedMotion(springDefault, null)).toBe(springDefault);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `corepack pnpm vitest run src/ui/motion.test.ts`
Expected: FAIL, "Failed to resolve import ./motion".

- [ ] **Step 3: Implement**

```ts
// src/ui/motion.ts
// Shared motion vocabulary (DESIGN.md › Motion). Components import these
// presets instead of inventing durations or easings.
import type { Transition } from 'motion/react';

export const EASE_OUT = [0.22, 1, 0.36, 1] as const;
export const EASE_SHEET = [0.32, 0.72, 0, 1] as const;

/** All interactive motion: critically damped, interruptible. */
export const springDefault: Transition = { type: 'spring', bounce: 0, duration: 0.35 };

/** Only after a physical flick/drag carried momentum. */
export const springMomentum: Transition = { type: 'spring', bounce: 0.2, duration: 0.4 };

export const durations = { press: 0.1, micro: 0.2, standard: 0.4, panel: 0.6 } as const;

/** Glass surfaces arrive as a material: opacity + scale + blur together. */
export const materialize = {
  initial: { opacity: 0, scale: 0.94, filter: 'blur(6px)' },
  animate: { opacity: 1, scale: 1, filter: 'blur(0px)' },
  exit: { opacity: 0, scale: 0.96, filter: 'blur(6px)' },
} as const;

/** prefers-reduced-motion: swap any movement for a short cross-fade. */
export function withReducedMotion(transition: Transition, reduced: boolean | null): Transition {
  return reduced ? { duration: 0.15, ease: 'linear' } : transition;
}
```

- [ ] **Step 4: Run test**

Run: `corepack pnpm vitest run src/ui/motion.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ui/motion.ts src/ui/motion.test.ts
git commit -m "feat(ui): shared motion presets"
```

---

### Task 4: `Glass` surface primitive

**Files:** Create `src/ui/glass.tsx`, `src/ui/glass.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// src/ui/glass.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Glass } from './glass';

describe('Glass', () => {
  it('renders the chrome material by default', () => {
    render(<Glass data-testid="g">x</Glass>);
    const el = screen.getByTestId('g');
    expect(el).toHaveClass('glass');
    expect(el).not.toHaveClass('glass-heavy');
    expect(el.tagName).toBe('DIV');
  });

  it('supports the heavy variant and a semantic element', () => {
    render(
      <Glass as="aside" variant="heavy" data-testid="g">
        x
      </Glass>,
    );
    const el = screen.getByTestId('g');
    expect(el).toHaveClass('glass', 'glass-heavy');
    expect(el.tagName).toBe('ASIDE');
  });

  it('tracks the pointer for the specular highlight only when enabled', () => {
    render(
      <Glass specular data-testid="g">
        x
      </Glass>,
    );
    const el = screen.getByTestId('g');
    expect(el).toHaveClass('glass-specular');
    fireEvent.pointerMove(el, { clientX: 40, clientY: 12 });
    expect(el.style.getPropertyValue('--spec-x')).toBe('40px');
    expect(el.style.getPropertyValue('--spec-y')).toBe('12px');
  });

  it('does not set specular vars when disabled', () => {
    render(<Glass data-testid="g">x</Glass>);
    const el = screen.getByTestId('g');
    fireEvent.pointerMove(el, { clientX: 40, clientY: 12 });
    expect(el.style.getPropertyValue('--spec-x')).toBe('');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `corepack pnpm vitest run src/ui/glass.test.tsx`
Expected: FAIL, cannot resolve `./glass`.

- [ ] **Step 3: Implement**

```tsx
// src/ui/glass.tsx
import * as React from 'react';
import { cn } from './utils';

type GlassElement = 'div' | 'aside' | 'header' | 'section' | 'form' | 'nav';

export interface GlassProps extends React.HTMLAttributes<HTMLElement> {
  as?: GlassElement;
  /** chrome: toolbars/composer/popovers · heavy: structural regions (sidebar). */
  variant?: 'chrome' | 'heavy';
  /** Liquid-Glass light response: a soft highlight follows the pointer. */
  specular?: boolean;
}

/** Floating translucent chrome (DESIGN.md › Elevation & Depth). Never put data on it. */
export const Glass = React.forwardRef<HTMLElement, GlassProps>(function Glass(
  { as = 'div', variant = 'chrome', specular = false, className, onPointerMove, ...props },
  ref,
) {
  const handlePointerMove = (e: React.PointerEvent<HTMLElement>) => {
    if (specular) {
      const rect = e.currentTarget.getBoundingClientRect();
      e.currentTarget.style.setProperty('--spec-x', `${e.clientX - rect.left}px`);
      e.currentTarget.style.setProperty('--spec-y', `${e.clientY - rect.top}px`);
    }
    onPointerMove?.(e);
  };
  return React.createElement(as, {
    ref,
    'data-glass': variant,
    className: cn('glass', variant === 'heavy' && 'glass-heavy', specular && 'glass-specular', className),
    onPointerMove: handlePointerMove,
    ...props,
  });
});
```

- [ ] **Step 4: Run test**

Run: `corepack pnpm vitest run src/ui/glass.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ui/glass.tsx src/ui/glass.test.tsx
git commit -m "feat(ui): Glass surface primitive with specular highlight"
```

---

### Task 5: DESIGN.md button variants

**Files:** Modify `src/ui/button.tsx`; Create `src/ui/button.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// src/ui/button.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Button } from './button';

describe('Button (DESIGN.md variants)', () => {
  it('primary is a clay pill with press feedback', () => {
    render(<Button>Approve</Button>);
    const b = screen.getByRole('button', { name: 'Approve' });
    expect(b).toHaveClass('rounded-full', 'bg-primary', 'text-primary-foreground', 'active:scale-[.97]');
  });

  it('pill shows selected state via data-selected', () => {
    render(
      <Button variant="pill" data-selected="true">
        Last quarter
      </Button>,
    );
    const b = screen.getByRole('button', { name: 'Last quarter' });
    expect(b).toHaveClass('data-[selected=true]:bg-primary');
    expect(b).toHaveAttribute('data-selected', 'true');
  });

  it('send is a 36px circle', () => {
    render(<Button variant="send" size="send" aria-label="Send" />);
    expect(screen.getByRole('button', { name: 'Send' })).toHaveClass('h-9', 'w-9', 'rounded-full');
  });

  it('keeps legacy variants working (outline, destructive, ghost)', () => {
    render(
      <>
        <Button variant="outline">o</Button>
        <Button variant="destructive">d</Button>
        <Button variant="ghost">g</Button>
      </>,
    );
    expect(screen.getByRole('button', { name: 'd' })).toHaveClass('bg-destructive');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `corepack pnpm vitest run src/ui/button.test.tsx`
Expected: FAIL (no `rounded-full` / no `pill` variant).

- [ ] **Step 3: Replace `buttonVariants` in `src/ui/button.tsx`** (keep the component and exports unchanged)

```tsx
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium transition-[transform,background-color,border-color,color,filter] duration-200 ease-out active:scale-[.97] active:duration-100 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/15 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default: 'rounded-full bg-primary text-primary-foreground hover:brightness-105',
        pill: 'rounded-full border border-border bg-card text-body hover:border-primary hover:text-ink data-[selected=true]:border-primary data-[selected=true]:bg-primary data-[selected=true]:text-primary-foreground',
        send: 'rounded-full bg-primary text-primary-foreground shadow-[0_4px_14px_hsl(var(--primary)/0.35)]',
        ghost: 'rounded-full text-ink hover:bg-foreground/5',
        outline: 'rounded-full border border-border bg-card text-ink hover:bg-foreground/5',
        secondary: 'rounded-full bg-secondary text-secondary-foreground hover:bg-secondary/80',
        destructive: 'rounded-full bg-destructive text-destructive-foreground hover:brightness-105',
        link: 'text-primary-text underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-9 px-4 text-label',
        sm: 'h-8 px-3 text-label',
        lg: 'h-10 px-6 text-sm',
        icon: 'h-9 w-9 rounded-full',
        send: 'h-9 w-9',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
);
```

- [ ] **Step 4: Run test + full suite**

Run: `corepack pnpm vitest run src/ui/button.test.tsx && corepack pnpm test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ui/button.tsx src/ui/button.test.tsx
git commit -m "feat(ui): DESIGN.md button variants (pill, send, press scale)"
```

---

### Task 6: Toolbar, Popover, Toaster primitives + exports

**Files:** Create `src/ui/toolbar.tsx`, `src/ui/toolbar.test.tsx`, `src/ui/popover.tsx`, `src/ui/popover.test.tsx`, `src/ui/toaster.tsx`; Modify `src/ui/index.ts`

- [ ] **Step 1: Write failing tests**

```tsx
// src/ui/toolbar.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Toolbar } from './toolbar';

describe('Toolbar', () => {
  it('renders a floating glass capsule with a serif title and actions', () => {
    render(
      <Toolbar title="Q3 revenue review">
        <button type="button">Search</button>
      </Toolbar>,
    );
    const heading = screen.getByRole('heading', { name: 'Q3 revenue review' });
    expect(heading).toHaveClass('font-serif');
    const bar = heading.closest('header');
    expect(bar).toHaveClass('glass', 'glass-specular', 'rounded-glass');
    expect(screen.getByRole('button', { name: 'Search' })).toBeInTheDocument();
  });
});
```

```tsx
// src/ui/popover.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Popover, PopoverContent, PopoverTrigger } from './popover';

describe('Popover', () => {
  it('materializes glass content from its trigger', async () => {
    render(
      <Popover>
        <PopoverTrigger>corporate_revenue</PopoverTrigger>
        <PopoverContent>Sum of paid B2B orders</PopoverContent>
      </Popover>,
    );
    await userEvent.click(screen.getByText('corporate_revenue'));
    const content = await screen.findByText('Sum of paid B2B orders');
    expect(content).toHaveClass('glass', 'rounded-feature');
  });
});
```

- [ ] **Step 2: Check `@testing-library/user-event` is available, add if not**

Run: `ls node_modules/@testing-library/ | grep user-event || corepack pnpm add -D @testing-library/user-event`
Expected: package present afterwards.

- [ ] **Step 3: Run tests to verify failure**

Run: `corepack pnpm vitest run src/ui/toolbar.test.tsx src/ui/popover.test.tsx`
Expected: FAIL, modules not found.

- [ ] **Step 4: Implement the three primitives**

```tsx
// src/ui/toolbar.tsx
import * as React from 'react';
import { Glass } from './glass';
import { cn } from './utils';

interface ToolbarProps {
  title: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}

/** Floating glass page toolbar (DESIGN.md › glass-toolbar) plus the scroll-edge
 * blur beneath it. Place inside a `relative` page container; content below
 * reserves 84px (`pt-[84px]`) so nothing hides under the glass at rest. */
export function Toolbar({ title, children, className }: ToolbarProps) {
  return (
    <>
      <div aria-hidden className="scroll-edge-top pointer-events-none absolute inset-x-0 top-0 z-[5] h-20" />
      <Glass
        as="header"
        specular
        className={cn(
          'absolute inset-x-3.5 top-2.5 z-10 flex h-[52px] items-center gap-2 rounded-glass pl-[18px] pr-2',
          className,
        )}
      >
        <h1 className="min-w-0 flex-1 truncate font-serif text-section text-ink">{title}</h1>
        {children}
      </Glass>
    </>
  );
}
```

```tsx
// src/ui/popover.tsx
import * as React from 'react';
import * as PopoverPrimitive from '@radix-ui/react-popover';
import { cn } from './utils';

const Popover = PopoverPrimitive.Root;
const PopoverTrigger = PopoverPrimitive.Trigger;
const PopoverAnchor = PopoverPrimitive.Anchor;

/** Glass popover that grows out of its trigger (origin = trigger) and
 * materializes (blur + scale + fade). DESIGN.md › glass-popover. */
const PopoverContent = React.forwardRef<
  React.ElementRef<typeof PopoverPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
>(({ className, align = 'start', sideOffset = 8, ...props }, ref) => (
  <PopoverPrimitive.Portal>
    <PopoverPrimitive.Content
      ref={ref}
      align={align}
      sideOffset={sideOffset}
      className={cn(
        'glass z-50 w-72 origin-[--radix-popover-content-transform-origin] rounded-feature p-3 text-label text-body outline-none',
        'data-[state=open]:animate-materialize-in data-[state=closed]:animate-materialize-out',
        className,
      )}
      {...props}
    />
  </PopoverPrimitive.Portal>
));
PopoverContent.displayName = 'PopoverContent';

export { Popover, PopoverTrigger, PopoverAnchor, PopoverContent };
```

```tsx
// src/ui/toaster.tsx
import { Toaster as Sonner, toast } from 'sonner';

/** Glass toasts, bottom-right, stacking. Only for completions that happen away
 * from their trigger (DESIGN.md › toast); in-place feedback morphs instead. */
export function Toaster() {
  return (
    <Sonner
      position="bottom-right"
      gap={10}
      toastOptions={{
        unstyled: true,
        classNames: {
          toast: 'glass flex w-[300px] items-center gap-2.5 rounded-lg px-3.5 py-3 text-label text-ink',
          title: 'font-medium',
          description: 'text-caption text-muted-foreground',
          icon: 'text-positive',
        },
      }}
    />
  );
}

export { toast };
```

- [ ] **Step 5: Export from `src/ui/index.ts`** (append)

```ts
export { Glass, type GlassProps } from './glass';
export { Toolbar } from './toolbar';
export { Popover, PopoverTrigger, PopoverAnchor, PopoverContent } from './popover';
export { Toaster, toast } from './toaster';
export {
  EASE_OUT,
  EASE_SHEET,
  durations,
  materialize,
  springDefault,
  springMomentum,
  withReducedMotion,
} from './motion';
```

- [ ] **Step 6: Run tests**

Run: `corepack pnpm vitest run src/ui && corepack pnpm typecheck`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/ui package.json pnpm-lock.yaml
git commit -m "feat(ui): glass Toolbar, Popover and Toaster primitives"
```

---

### Task 7: Lint guard against hard-coded hex in features

**Files:** Modify `eslint.config.js`, `src/features/auth/login.tsx`

- [ ] **Step 1: Add the rule to the `src/features/**` config block** (inside its `rules`, next to `no-restricted-imports`)

```js
      'no-restricted-syntax': [
        'error',
        {
          selector: 'Literal[value=/#[0-9a-fA-F]{3,8}\\b/]',
          message: 'DESIGN.md: use design tokens (Tailwind token classes / CSS vars), never hex colors in features.',
        },
        {
          selector: 'TemplateElement[value.raw=/#[0-9a-fA-F]{3,8}\\b/]',
          message: 'DESIGN.md: use design tokens (Tailwind token classes / CSS vars), never hex colors in features.',
        },
      ],
```

- [ ] **Step 2: Run lint to see the expected failures**

Run: `corepack pnpm lint`
Expected: FAIL only in `src/features/auth/login.tsx` (the Google "G" mark fills).

- [ ] **Step 3: Scope an exemption around the official brand mark in `login.tsx`**

Add directly above the `GoogleMark` function:
```tsx
/* eslint-disable no-restricted-syntax -- official Google "G" brand colors, not design tokens */
```
and directly after the function's closing brace:
```tsx
/* eslint-enable no-restricted-syntax */
```

- [ ] **Step 4: Run lint**

Run: `corepack pnpm lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eslint.config.js src/features/auth/login.tsx
git commit -m "chore(lint): forbid hex colors in features (DESIGN.md tokens only)"
```

---

### Task 8: Chat thread list (moved out of ChatPage, URL-driven)

**Files:** Create `src/features/chat/components/chat-thread-list.tsx`, `src/features/chat/components/chat-thread-list.test.tsx` (code below shows `./chat-thread-list`; it's in `components/`)

- [ ] **Step 1: Write the failing test**

```tsx
// src/features/chat/chat-thread-list.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ChatThreadList } from './chat-thread-list';

vi.mock('@/api/hooks/use-chat-sessions', () => ({
  useChatSessions: () => ({
    data: [
      { id: 's1', title: 'Q3 revenue review', created_at: '', updated_at: new Date().toISOString() },
      { id: 's2', title: 'ROAS by channel', created_at: '', updated_at: new Date().toISOString() },
    ],
  }),
  useDeleteChatSession: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <ChatThreadList />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ChatThreadList', () => {
  it('lists sessions and marks the one in the URL as current', () => {
    renderAt('/ask/s2');
    expect(screen.getByText('Q3 revenue review')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /ROAS by channel/ })).toHaveAttribute('aria-current', 'page');
  });

  it('navigates to a thread and to a new chat', async () => {
    renderAt('/ask');
    await userEvent.click(screen.getByRole('link', { name: /Q3 revenue review/ }));
    expect(screen.getByTestId('where')).toHaveTextContent('/ask/s1');
    await userEvent.click(screen.getByRole('button', { name: /new chat/i }));
    expect(screen.getByTestId('where')).toHaveTextContent('/ask');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `corepack pnpm vitest run src/features/chat/chat-thread-list.test.tsx`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement** (delete flow moved verbatim from `index.tsx`)

```tsx
// src/features/chat/chat-thread-list.tsx
import { useState } from 'react';
import { Link, useMatch, useNavigate } from 'react-router-dom';
import { Plus, Trash2 } from 'lucide-react';
import {
  Button,
  cn,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/ui';
import { formatRelativeTime } from '@/lib/utils';
import { useChatSessions, useDeleteChatSession } from '@/api/hooks/use-chat-sessions';
import type { ChatSession } from '@/api/chat';

/** Threads for the shell sidebar. The active thread comes from the URL
 * (/ask/:sessionId) so the list and the chat page never share state. */
export function ChatThreadList() {
  const navigate = useNavigate();
  const activeId = useMatch('/ask/:sessionId')?.params.sessionId ?? null;
  const { data: sessions = [] } = useChatSessions();
  const deleteSession = useDeleteChatSession();
  const [pendingDelete, setPendingDelete] = useState<ChatSession | null>(null);

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    await deleteSession.mutateAsync(pendingDelete.id);
    if (activeId === pendingDelete.id) navigate('/ask');
    setPendingDelete(null);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center px-2.5 pb-1.5 pt-4">
        <span className="flex-1 text-caption uppercase tracking-[0.06em] text-muted-2">Threads</span>
        <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => navigate('/ask')}>
          <Plus /> New chat
        </Button>
      </div>
      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto pb-2">
        {sessions.length === 0 && (
          <p className="px-2.5 py-4 text-caption text-muted-foreground">No conversations yet.</p>
        )}
        {sessions.map((s) => {
          const current = s.id === activeId;
          return (
            <div key={s.id} className="group relative">
              <Link
                to={`/ask/${s.id}`}
                aria-current={current ? 'page' : undefined}
                className={cn(
                  'flex items-center gap-2 rounded-md px-2.5 py-1.5 text-label transition-colors duration-200',
                  current
                    ? 'bg-card text-ink shadow-[0_0_0_1px_hsl(var(--border))]'
                    : 'text-muted-foreground hover:bg-foreground/5 hover:text-ink',
                )}
              >
                <span className="min-w-0 flex-1 truncate">{s.title || 'Untitled chat'}</span>
                <span className="font-mono text-[10.5px] text-muted-2 group-hover:invisible">
                  {formatRelativeTime(s.updated_at)}
                </span>
              </Link>
              <button
                type="button"
                aria-label={`Delete ${s.title || 'chat'}`}
                onClick={() => setPendingDelete(s)}
                className="absolute right-1.5 top-1/2 hidden -translate-y-1/2 rounded-full p-1 text-muted-foreground hover:text-negative group-hover:block"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </div>

      <Dialog open={!!pendingDelete} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this chat?</DialogTitle>
            <DialogDescription>
              “{pendingDelete?.title || 'Untitled chat'}” and its messages will be permanently removed.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setPendingDelete(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => void confirmDelete()}
              disabled={deleteSession.isPending}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

- [ ] **Step 4: Run test**

Run: `corepack pnpm vitest run src/features/chat/chat-thread-list.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/features/chat/chat-thread-list.tsx src/features/chat/chat-thread-list.test.tsx
git commit -m "feat(chat): URL-driven thread list for the shell sidebar"
```

---

### Task 9: ChatPage reads the session from the URL

**Files:** Rewrite `src/features/chat/index.tsx`; Modify `src/features/chat/chat-panel.tsx` (one line)

- [ ] **Step 1: Rewrite `index.tsx`**

```tsx
// Public interface of the chat feature: the chat page + the sidebar thread list.
import { useCallback, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Toolbar } from '@/ui';
import { useChatSessions, useCreateChatSession } from '@/api/hooks/use-chat-sessions';
import { ChatPanel } from './components/chat-panel';

export { ChatThreadList } from './components/chat-thread-list';

export default function ChatPage() {
  const { sessionId = null } = useParams();
  const navigate = useNavigate();
  const { data: sessions = [] } = useChatSessions();
  const createSession = useCreateChatSession();
  const ensuringRef = useRef<Promise<string> | null>(null);

  // A draft (/ask) has no session until the first message is sent. The route
  // is /ask/:sessionId? (one route), so swapping the param does NOT remount the
  // panel and the in-flight stream survives.
  const ensureSession = useCallback((): Promise<string> => {
    if (ensuringRef.current) return ensuringRef.current;
    const p = createSession
      .mutateAsync(undefined)
      .then((s) => {
        navigate(`/ask/${s.id}`, { replace: true });
        ensuringRef.current = null;
        return s.id;
      })
      .catch((err) => {
        ensuringRef.current = null;
        throw err;
      });
    ensuringRef.current = p;
    return p;
  }, [createSession, navigate]);

  const title = sessions.find((s) => s.id === sessionId)?.title || 'New chat';

  return (
    <div className="relative h-full min-h-0">
      <Toolbar title={title} />
      <ChatPanel sessionId={sessionId} ensureSession={sessionId ? undefined : ensureSession} />
    </div>
  );
}
```

- [ ] **Step 2: Reserve toolbar clearance in `components/chat-panel.tsx`** (or whichever split component owns the scroll content)

Change the inner content container class `mx-auto w-full max-w-3xl space-y-4 px-4 py-6` to:
```
mx-auto w-full max-w-3xl space-y-4 px-4 pb-6 pt-[84px]
```

- [ ] **Step 3: Typecheck + tests**

Run: `corepack pnpm typecheck && corepack pnpm test`
Expected: PASS (use-chat-turn tests unaffected).

- [ ] **Step 4: Commit**

```bash
git add src/features/chat/index.tsx src/features/chat/chat-panel.tsx
git commit -m "refactor(chat): session id lives in the URL (/ask/:sessionId?)"
```

---

### Task 10: Floating glass shell

**Files:** Rewrite `src/features/layout/shell.tsx`; Modify `src/features/layout/index.ts`; Create `src/features/layout/shell.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// src/features/layout/shell.test.tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { MessageCircle } from 'lucide-react';
import { describe, expect, it } from 'vitest';
import { ThemeProvider } from '@/lib/theme-provider';
import Shell from './shell';

const nav = [{ to: '/ask', label: 'Ask Atlas', icon: MessageCircle }];

describe('Shell', () => {
  it('renders a floating heavy-glass sidebar with nav, threads slot and content', () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={['/ask']}>
          <Shell user={null} onSignOut={() => {}} nav={nav} threads={<p>threads-slot</p>}>
            <p>page-content</p>
          </Shell>
        </MemoryRouter>
      </ThemeProvider>,
    );
    const sidebar = screen.getByRole('complementary');
    expect(sidebar).toHaveClass('glass', 'glass-heavy', 'rounded-shell');
    expect(screen.getByRole('link', { name: /Ask Atlas/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('threads-slot')).toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveTextContent('page-content');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `corepack pnpm vitest run src/features/layout/shell.test.tsx`
Expected: FAIL (`nav` prop unknown / no complementary role).

- [ ] **Step 3: Rewrite `shell.tsx`** (ThemeToggle, DropdownMenuCheckItem and UserMenu bodies are kept from the current file, unchanged except the trigger buttons below)

```tsx
import type { LucideIcon } from 'lucide-react';
import { LogOut, Monitor, Moon, Sun } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Glass,
} from '@/ui';
import { useTheme } from '@/lib/theme-provider';

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

interface ShellUser {
  name: string;
  email: string;
  avatar: string;
}

interface ShellProps {
  user: ShellUser | null;
  onSignOut: () => void;
  nav: NavItem[];
  /** Feature-provided sidebar content (e.g. chat threads), composed in App.tsx. */
  threads?: React.ReactNode;
  children: React.ReactNode;
}

/** App frame (DESIGN.md › Layout): 10px inset, floating heavy-glass sidebar,
 * rounded main pane. Features plug in via props so layout stays decoupled. */
export default function Shell({ user, onSignOut, nav, threads, children }: ShellProps) {
  return (
    <div className="flex h-screen gap-2.5 p-2.5">
      <Glass
        as="aside"
        variant="heavy"
        specular
        className="flex w-[236px] shrink-0 flex-col rounded-shell px-2.5 py-3.5 max-[999px]:hidden"
      >
        <div className="flex items-center gap-2.5 px-2.5 pb-3.5 pt-1">
          <span aria-hidden className="h-2.5 w-2.5 rotate-45 rounded-[3px] bg-primary" />
          <span className="font-serif text-[21px] leading-none text-ink">Atlas</span>
        </div>
        <nav className="space-y-0.5" aria-label="Primary">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-[background-color,transform] duration-200 active:scale-[.97]',
                  isActive
                    ? 'bg-card text-ink shadow-[0_0_0_1px_hsl(var(--border)),0_1px_3px_rgba(0,0,0,0.06)]'
                    : 'text-body hover:bg-foreground/5',
                )
              }
            >
              <Icon className="h-4 w-4 opacity-75" />
              {label}
            </NavLink>
          ))}
        </nav>
        {threads}
        <div className="mt-auto flex items-center gap-1 border-t border-border/60 px-1 pt-2.5">
          <UserMenu user={user} onSignOut={onSignOut} />
          <span className="min-w-0 flex-1 truncate text-label text-muted-foreground">{user?.name}</span>
          <ThemeToggle />
        </div>
      </Glass>
      <main className="relative min-w-0 flex-1 overflow-hidden rounded-shell">{children}</main>
    </div>
  );
}
```

Keep `ThemeToggle`, `DropdownMenuCheckItem` and `UserMenu` from the current file. In `ThemeToggle` change `<Button variant="ghost" size="icon" aria-label="Toggle theme">` (no other change). In `DropdownMenuCheckItem` replace `'bg-accent text-accent-foreground'` with `'bg-primary/10 text-ink'`. In `UserMenu` replace the trigger class with
`'flex h-8 w-8 items-center justify-center overflow-hidden rounded-full border bg-card-2 text-caption font-medium transition-transform active:scale-95'`.

- [ ] **Step 4: Update `src/features/layout/index.ts`**

```ts
// Public interface of the layout feature.
export { default as Shell, type NavItem } from './shell';
```

- [ ] **Step 5: Run test**

Run: `corepack pnpm vitest run src/features/layout`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/features/layout
git commit -m "feat(layout): floating glass shell with nav and threads slot"
```

---

### Task 11: App routing + composition

**Files:** Rewrite `src/App.tsx`

- [ ] **Step 1: Rewrite**

```tsx
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { MessageCircle } from 'lucide-react';
import { queryClient } from '@/api/query-client';
import { ThemeProvider } from '@/lib/theme-provider';
import { Toaster } from '@/ui';
import { AuthProvider, LoginPage, ProtectedRoute, useAuth } from '@/features/auth';
import { Shell, type NavItem } from '@/features/layout';
import ChatPage, { ChatThreadList } from '@/features/chat';

// Tracks D1/E-fe append their entries here (Metrics, Overview).
const NAV: NavItem[] = [{ to: '/ask', label: 'Ask Atlas', icon: MessageCircle }];

/** Composition point: wires auth + chat into the layout so features stay decoupled. */
function AppShell() {
  const { user, signOut } = useAuth();
  return (
    <Shell user={user} onSignOut={() => void signOut()} nav={NAV} threads={<ChatThreadList />}>
      <Outlet />
    </Shell>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider defaultTheme="system">
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route
                element={
                  <ProtectedRoute>
                    <AppShell />
                  </ProtectedRoute>
                }
              >
                <Route index element={<Navigate to="/ask" replace />} />
                <Route path="ask/:sessionId?" element={<ChatPage />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
          <Toaster />
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 2: Full verification**

Run: `corepack pnpm test && corepack pnpm lint && corepack pnpm typecheck && corepack pnpm build`
Expected: all PASS.

- [ ] **Step 3: Visual check**

Run the app (`run` skill, or `corepack pnpm dev` with backend on :8081). Verify:
- floating glass sidebar with nav + threads
- glass toolbar showing the thread title
- starting a new chat moves the URL `/ask` → `/ask/<id>` **without** interrupting the stream
- light, dark, reduced-transparency (macOS: Accessibility → Display → Reduce transparency) and reduced-motion

- [ ] **Step 4: Commit**

```bash
git add src/App.tsx
git commit -m "feat(app): glass shell layout route and /ask/:sessionId? routing"
```

---

### Task 12: `PresetCard` primitive (shared by chat empty state + dashboard)

**Files:** Create `src/ui/preset-card.tsx`, `src/ui/preset-card.test.tsx`; Modify `src/ui/index.ts`

- [ ] **Step 1: Write the failing test**

```tsx
// src/ui/preset-card.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { PresetCard } from './preset-card';

describe('PresetCard (Higgsfield-style preset)', () => {
  it('is a button with title, description and a preview that plays on hover', async () => {
    const onSelect = vi.fn();
    render(<PresetCard title="Revenue review" description="Trend, drivers" preview="line" onSelect={onSelect} />);
    const card = screen.getByRole('button', { name: /Revenue review/ });
    expect(card).toHaveClass('group', 'rounded-feature');
    expect(card.querySelector('[data-preview="line"]')).not.toBeNull();
    await userEvent.click(card);
    expect(onSelect).toHaveBeenCalledOnce();
  });

  it.each(['line', 'bars', 'funnel'] as const)('renders the %s preview', (preview) => {
    render(<PresetCard title="t" preview={preview} onSelect={() => {}} />);
    expect(document.querySelector(`[data-preview="${preview}"]`)).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `corepack pnpm vitest run src/ui/preset-card.test.tsx`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

```tsx
// src/ui/preset-card.tsx
import { cn } from './utils';

export type PresetPreview = 'line' | 'bars' | 'funnel';

interface PresetCardProps {
  title: string;
  description?: string;
  preview: PresetPreview;
  onSelect: () => void;
  compact?: boolean;
}

/** Preset gallery card (DESIGN.md › preset-card): lifts on hover and plays a
 * preview of what the analysis produces. Purely presentational. */
export function PresetCard({ title, description, preview, onSelect, compact = false }: PresetCardProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="group overflow-hidden rounded-feature bg-card text-left shadow-[0_0_0_1px_hsl(var(--border)/0.6)] transition-[transform,box-shadow] duration-300 ease-out hover:-translate-y-[3px] hover:shadow-[0_0_0_1px_hsl(var(--border)),0_14px_34px_rgba(0,0,0,0.10)] active:scale-[.98] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/15"
    >
      <div className={cn('relative bg-card-2', compact ? 'h-20' : 'h-[108px]')}>
        <Preview kind={preview} />
      </div>
      <div className="px-3.5 pb-3.5 pt-3">
        <span className="block text-sm font-semibold text-ink">{title}</span>
        {description && <span className="block text-caption text-muted-foreground">{description}</span>}
      </div>
    </button>
  );
}

function Preview({ kind }: { kind: PresetPreview }) {
  const drawn =
    'transition-[stroke-dashoffset] duration-[1100ms] ease-out [stroke-dasharray:420] [stroke-dashoffset:420] group-hover:[stroke-dashoffset:0]';
  if (kind === 'line') {
    return (
      <svg data-preview="line" viewBox="0 0 200 108" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
        <path d="M10 88 C40 78,60 58,90 64 S140 28,190 22" fill="none" strokeWidth="2.2" strokeLinecap="round" className={cn('stroke-primary', drawn)} />
      </svg>
    );
  }
  if (kind === 'bars') {
    return (
      <svg data-preview="bars" viewBox="0 0 200 108" className="absolute inset-0 h-full w-full">
        {[[25, 40, 58], [65, 24, 74], [105, 54, 44], [145, 34, 64]].map(([x, y, h], i) => (
          <rect key={x} x={x} y={y} width="22" height={h} rx="5" style={{ transitionDelay: `${i * 50}ms` }}
            className="origin-bottom fill-primary/75 [transform-box:fill-box] [transform:scaleY(.25)] transition-transform duration-700 ease-out group-hover:[transform:scaleY(1)]" />
        ))}
      </svg>
    );
  }
  return (
    <svg data-preview="funnel" viewBox="0 0 200 108" className="absolute inset-0 h-full w-full">
      {[[20, 160, 0.85], [45, 118, 0.6], [70, 62, 0.4]].map(([y, w, o], i) => (
        <rect key={y} x="20" y={y} width={w} height="16" rx="5" style={{ opacity: o, transitionDelay: `${i * 60}ms` }}
          className="origin-left fill-primary [transform-box:fill-box] [transform:scaleX(.25)] transition-transform duration-700 ease-out group-hover:[transform:scaleX(1)]" />
      ))}
    </svg>
  );
}
```

- [ ] **Step 4: Export** (append to `src/ui/index.ts`)

```ts
export { PresetCard, type PresetPreview } from './preset-card';
```

- [ ] **Step 5: Run tests + commit**

Run: `corepack pnpm vitest run src/ui/preset-card.test.tsx && corepack pnpm lint`
Expected: PASS.

```bash
git add src/ui/preset-card.tsx src/ui/preset-card.test.tsx src/ui/index.ts
git commit -m "feat(ui): PresetCard with hover-play previews"
```

---

### Task 13: Shared freshness helpers (`src/lib/freshness.ts`)

Used by the chat (Track B) and dashboard (Track E-fe) features, so they live in `lib`.

**Files:** Create `src/lib/freshness.ts`, `src/lib/freshness.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
// src/lib/freshness.test.ts
import { describe, expect, it } from 'vitest';
import { freshnessLabel, isStale, parseFreshness } from './freshness';

const NOW = new Date('2026-10-08T12:00:00Z');

describe('freshness', () => {
  it('parses ISO and Postgres-style timestamps', () => {
    expect(parseFreshness('2026-10-08T10:00:00+00:00')?.toISOString()).toBe('2026-10-08T10:00:00.000Z');
    expect(parseFreshness('2026-10-08 10:00:00+00:00')?.toISOString()).toBe('2026-10-08T10:00:00.000Z');
    expect(parseFreshness('2h ago')).toBeNull();
    expect(parseFreshness(undefined)).toBeNull();
  });

  it('labels age compactly and passes through unparseable values', () => {
    expect(freshnessLabel('2026-10-08T11:59:30Z', NOW)).toBe('just now');
    expect(freshnessLabel('2026-10-08T10:00:00Z', NOW)).toBe('2h ago');
    expect(freshnessLabel('2026-10-06T12:00:00Z', NOW)).toBe('2d ago');
    expect(freshnessLabel('2h ago', NOW)).toBe('2h ago');
  });

  it('is stale after 24h; unknown freshness is never flagged', () => {
    expect(isStale('2026-10-07T11:00:00Z', NOW)).toBe(true);
    expect(isStale('2026-10-08T02:00:00Z', NOW)).toBe(false);
    expect(isStale('2h ago', NOW)).toBe(false);
    expect(isStale(undefined, NOW)).toBe(false);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `corepack pnpm vitest run src/lib/freshness.test.ts` → FAIL (module not found)

- [ ] **Step 3: Implement**

```ts
// src/lib/freshness.ts
// Provenance `freshness` is the newest-data timestamp a source reports
// (str(timestamp) from the connector). Stale = older than the source SLA.
export const STALE_AFTER_HOURS = 24;

export function parseFreshness(value: string | null | undefined): Date | null {
  if (!value) return null;
  const normalized = /^\d{4}-\d{2}-\d{2} \d/.test(value) ? value.replace(' ', 'T') : value;
  if (!/^\d{4}-\d{2}-\d{2}/.test(normalized)) return null;
  const date = new Date(normalized);
  return isNaN(date.getTime()) ? null : date;
}

export function freshnessLabel(value: string | null | undefined, now = new Date()): string {
  const date = parseFreshness(value);
  if (!date) return value ?? '';
  const minutes = Math.floor((now.getTime() - date.getTime()) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function isStale(value: string | null | undefined, now = new Date()): boolean {
  const date = parseFreshness(value);
  if (!date) return false;
  return now.getTime() - date.getTime() > STALE_AFTER_HOURS * 3_600_000;
}
```

- [ ] **Step 4: Run + commit**

Run: `corepack pnpm vitest run src/lib/freshness.test.ts` → PASS

```bash
git add src/lib/freshness.ts src/lib/freshness.test.ts
git commit -m "feat(lib): provenance freshness parsing and staleness"
```

---

## Self-review notes
- Spec §4 Phase 1 items 1–4 and 6 (tokens, fonts, ui primitives, shell, a11y media queries) → Tasks 1–7, 10. The §5 ESLint guard → Task 7.
- Chat restyle, streaming, steps, notices and provenance popover are Track B (`…-04-chat-experience.md`).

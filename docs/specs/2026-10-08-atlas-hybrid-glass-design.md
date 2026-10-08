# Atlas Hybrid Glass: design system adoption

**Date:** 2026-10-08 · **Status:** Approved direction, spec pending review · **Owner:** ashik@yougotagift.com

## 1. Decision

ygg-atlas adopts **Atlas Hybrid Glass** as its single UI standard, defined in [`/DESIGN.md`](../../DESIGN.md)
(Google DESIGN.md format, linted with `@google/design.md`). It's the "Hybrid" mode chosen from
live mockups (`docs/design/reference/atlas-hybrid-glass.html`, Mode ①):

- **Foundation, Apple glass:** a floating inset glass sidebar, toolbar and composer over solid content; scroll-edge blur;
  specular highlight; critically damped springs; press feedback; reduced-motion and reduced-transparency fallbacks.
- **Voice, Claude:** cream canvas, warm ink, a single clay primary (`#b45536`, WCAG AA), serif headings (Source Serif 4),
  blur-in streaming, "Worked for Ns" collapse, artifact side panel, editorial briefing.
- **Agency, Codex:** live step list with tool names, elapsed timer, send⇄stop, thread status, jobs tray,
  review-diff before any write action, mono ids.
- **Discovery, Higgsfield:** preset gallery cards with hover-play previews.
- **Trust, Atlas-native:** provenance chip + definition popover on every number, clarify-not-guess pills,
  denial-as-fact notice, freshness warnings.

Rejected: MiniMax per-source colors (they compete with the single primary), full Liquid Glass on every layer
(hurts readability of data), scroll-jacking/parallax/animated backgrounds (they conflict with apple-design §14).

Governance: the new `CLAUDE.md` § "Design standard" makes DESIGN.md mandatory for all UI work. Technique comes from
the vendored `.claude/skills/apple-design` (pinned `emilkowalski/skills@e8a175de`, MIT), and DESIGN.md wins any conflict.

## 2. Already done (this session)

| Item | Detail |
|---|---|
| `DESIGN.md` | Tokens (35 colors incl. dark twins, 10 type scales, radii, spacing, 26 components) + rules; lint: 0 errors |
| `CLAUDE.md` | Design-standard section + quality-gate line |
| Skill | `.claude/skills/apple-design/` (canned-reply block removed, precedence note added) |
| Reference | `docs/design/reference/atlas-hybrid-glass.html` (5 modes × 9 cases, origin overlay) |
| Dependencies | `motion` 14, `streamdown` 2.7, `@number-flow/react` 0.6, `sonner` 2, `cmdk` 1.1, `@radix-ui/react-popover`, `@fontsource-variable/inter`, `@fontsource-variable/source-serif-4`, `@fontsource-variable/jetbrains-mono` |

## 3. What exists today (constraints)

- SSE events: `token`, `tool_status` (tool name per call), `done` (content + provenance), `blocked` (reason), `error`.
  There's **no upfront plan event, no clarify event, and no structured artifact payload**.
- The agent is **read-only**. There are no write/schedule/send actions yet, so the review card has nothing to review.
- There's no dashboard page. The UI today is a chat shell (`features/chat`, `features/layout`, `features/auth`) on shadcn-style `ui/`.
- `features/chat/markdown-stream.ts` stabilizes partial markdown by hand. `streamdown` supersedes it.

## 4. Rollout phases

Each phase gets its own implementation plan in `docs/plans/`. **This spec's plan covers Phase 1 only.**

### Phase 1: Foundation + chat (everything today's backend supports)
1. **Tokens:** `frontend/src/index.css` carries DESIGN.md tokens as CSS variables (light, dark, warm ambient wash).
   `tailwind.config.js` maps semantic names (`canvas`, `card`, `card-2`, `ink`, `body`, `muted`, `primary`, `positive`,
   `negative`, `warning`, `glass*`) and the radii/spacing scales. The old shadcn teal palette is removed in place.
2. **Fonts:** self-hosted Inter, Source Serif 4 and JetBrains Mono (fontsource, already installed). `font-variant-numeric: tabular-nums` on numeric UI.
3. **`ui/` primitives (public via `ui/index.ts`):**
   - `Glass` (variants: `chrome`, `heavy`, `popover`; specular highlight opt-in; reduced-transparency fallback)
   - `motion.ts` presets (`springDefault`, `springMomentum`, `press`, `materialize`, easing constants)
   - `Button` variants `primary | pill | pill-selected | icon | send` per DESIGN.md
   - `Popover` (Radix, origin-aware materialize), `Toaster` (sonner, glass)
4. **Shell (`features/layout`):** floating glass sidebar with thread list + status dots; glass toolbar; 10px shell inset;
   scroll-edge blur; theme toggle cross-fade.
5. **Chat (`features/chat`):**
   - `usePacedText`: adaptive pacing buffer (40ms tick, 1→2→3 words by backlog), driven by `token` events.
   - Streaming render with `streamdown` (replaces `markdown-stream.ts` + its test, refactored in place). Word-chunk
     blur-in reveal. Existing text never re-animates. Caret dot. Auto-scroll only within 240px of the bottom.
   - **Steps block** built from successive `tool_status` events (each new tool = new step, the previous one ✓). Mono tool
     names, shimmer header, elapsed timer. It collapses to "Worked for Ns · N steps" on `done` and can be expanded again.
   - Composer: glass, send⇄stop morph with ring (wired to the existing abort), focus ring, elapsed timer.
   - Provenance chips restyled and given a Radix popover (metric id, source, freshness). Chips turn amber and show a
     `notice-warning` when freshness exceeds the source SLA (default 24h; threshold is a constant in the chat feature).
   - `blocked` renders as `notice-denied`. `error` renders as a neutral notice with retry.
   - Message feedback: icon morph in place (copy → ✓, thumbs fill). No toast for in-place feedback.
6. **Accessibility:** reduced-motion (cross-fades, instant digits, no blur), reduced-transparency (solid chrome),
   `prefers-contrast: more`, visible focus, 36px minimum targets.

### Phase 2: Structured answers (needs backend events)
- `clarify` SSE event → metric/period choice pills (guardrail #1 made visible).
- Structured `artifact` payload → artifact card + right side panel (export, save).
- `plan` SSE event → steps pre-announced as a checklist before execution.
- ⌘K palette (`cmdk`) over metrics, threads and asks. Metrics catalog page (inset grouped list) backed by a registry list endpoint.
- Number ↔ provenance-chip hover linking (needs number spans tagged with a metric id from the backend).

### Phase 3: Dashboard + agent actions
- Overview dashboard: briefing card, KPI cards with `@number-flow/react`, chart morph, top-N table, preset gallery.
- Background jobs tray + scheduled threads.
- Review card + diff for agent write/schedule/send actions, built when such actions exist (each needs its own guardrail spec).

## 5. Architecture & boundaries

- Direction stays `features → api/lib → ui`. Everything visual lives in `ui/`. Features compose primitives and never
  style raw hex. `usePacedText` and the steps reducer are pure and live inside `features/chat` (not exported).
- One motion vocabulary: components import presets from `ui/motion.ts`. No inline durations.
- ESLint guard (Phase 1): restrict hex color literals in `features/**` className and style strings (custom
  `no-restricted-syntax` regex) so token-only use is enforced, not just documented.

## 6. Testing

- **Unit (vitest):**
  - `usePacedText`: pacing rates by backlog, flush on `done`, no dropped or duplicated tokens.
  - Steps reducer: tool_status sequence → steps, collapse on done.
  - Freshness threshold → stale state.
  - Reduced-motion branch (no blur class).
  - `blocked`/`error` → notice variants.
- **Component:**
  - Provenance popover opens from the chip.
  - Send⇄stop calls abort.
  - Composer focus ring.
  - Glass falls back to solid under reduced transparency (class/attribute assertion).
- **Visual check:** run the app (`run` skill). Check light, dark, reduced-motion and reduced-transparency against the reference mockup.
- **Evals:** no agent/prompt change in Phase 1, so goldens are unaffected. Phase 2 events get golden coverage.
- Coverage >80% on new code. `pnpm lint && pnpm typecheck` clean. DESIGN.md lint 0 errors.

## 7. Risks

| Risk | Mitigation |
|---|---|
| `backdrop-filter` cost on low-end GPUs | Glass limited to ~5 floating surfaces; no glass inside scrolling lists; reduced-transparency path |
| Pacing hides real latency | Buffer releases faster as backlog grows; flushes immediately on `done` |
| streamdown migration regresses partial-markdown handling | Port the existing `markdown-stream.test.ts` cases as acceptance tests before deleting the old module |
| Reference mockup drifts from tokens over time | Mockup uses DESIGN.md clay (#b45536); DESIGN.md stays authoritative |

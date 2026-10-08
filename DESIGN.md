---
version: alpha
name: Atlas Hybrid Glass
description: >-
  The ygg-atlas UI standard. Apple glass is the foundation (floating translucent chrome over solid
  content), dressed in Claude's warm editorial voice (cream canvas, serif headings, clay accent,
  soft streaming), with Codex's agent transparency (live plans, timers, review-before-apply,
  background jobs) and Higgsfield's preset gallery. Every number carries provenance. Data never
  sits on glass.

colors:
  # Light (default)
  canvas: "#faf9f5"
  card: "#ffffff"
  card-2: "#f7f3ec"
  ink: "#141413"
  body: "#3d3d3a"
  muted: "#6c6a64"
  muted-2: "#8e8b82"
  hairline: "#14141314"
  hairline-soft: "#1414130d"
  primary: "#b45536"
  primary-soft: "#b455361f"
  on-primary: "#ffffff"
  positive: "#3f7d4e"
  negative: "#b4452f"
  warning: "#b7791f"
  glass: "#ffffff9e"
  glass-heavy: "#ffffffb8"
  glass-edge: "#ffffffcc"
  scrim: "#0000002e"
  # Dark
  canvas-dark: "#1a1917"
  card-dark: "#252320"
  card-2-dark: "#2b2925"
  ink-dark: "#f3f0ea"
  body-dark: "#d6d2ca"
  muted-dark: "#a09d96"
  muted-2-dark: "#7d7a73"
  hairline-dark: "#ffffff14"
  hairline-soft-dark: "#ffffff0d"
  primary-on-dark: "#d97a57"
  primary-soft-dark: "#d97a5733"
  positive-dark: "#7cc28c"
  negative-dark: "#e48a72"
  warning-dark: "#e0a84a"
  glass-dark: "#28262291"
  glass-heavy-dark: "#242320b3"
  glass-edge-dark: "#ffffff1a"

typography:
  display:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: 32px
    fontWeight: 400
    lineHeight: 1.15
    letterSpacing: -0.01em
  title:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: 23px
    fontWeight: 400
    lineHeight: 1.25
    letterSpacing: -0.01em
  section:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: 19px
    fontWeight: 400
    lineHeight: 1.3
    letterSpacing: -0.005em
  answer:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, system-ui, sans-serif"
    fontSize: 15.5px
    fontWeight: 400
    lineHeight: 1.65
    letterSpacing: 0
  body:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, system-ui, sans-serif"
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0
  label:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, system-ui, sans-serif"
    fontSize: 13px
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: 0
  caption:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, system-ui, sans-serif"
    fontSize: 11.5px
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: 0.005em
  metric-xl:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, system-ui, sans-serif"
    fontSize: 32px
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: -0.03em
    fontFeature: '"tnum"'
  metric-lg:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, system-ui, sans-serif"
    fontSize: 27px
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: -0.025em
    fontFeature: '"tnum"'
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, Menlo, monospace"
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: 0

rounded:
  sm: 8px
  md: 12px
  lg: 16px
  card: 18px
  shell: 22px
  glass: 26px
  feature: 24px
  pill: 9999px

spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 20px
  xl: 24px
  xxl: 32px
  section: 48px
  shell-gap: 10px
  chrome-clearance: 84px
  composer-clearance: 190px

components:
  shell-sidebar:
    backgroundColor: "{colors.glass-heavy}"
    textColor: "{colors.body}"
    typography: "{typography.body}"
    rounded: "{rounded.shell}"
    padding: 14px 10px
    width: 236px
  glass-toolbar:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.ink}"
    typography: "{typography.section}"
    rounded: "{rounded.glass}"
    height: 52px
    padding: 0 8px 0 18px
  glass-composer:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.ink}"
    typography: "{typography.answer}"
    rounded: "{rounded.glass}"
    padding: 12px 12px 10px 18px
  glass-popover:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.body}"
    typography: "{typography.label}"
    rounded: "{rounded.feature}"
    padding: 10px
  briefing-card:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.body}"
    typography: "{typography.answer}"
    rounded: "{rounded.feature}"
    padding: 18px 20px
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.card}"
    padding: 16px 18px
  kpi-card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    typography: "{typography.metric-lg}"
    rounded: "{rounded.card}"
    padding: 14px 16px
  metric-card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    typography: "{typography.metric-xl}"
    rounded: "{rounded.card}"
    padding: 14px 16px
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: 8px 16px
  button-pill:
    backgroundColor: "{colors.card}"
    textColor: "{colors.body}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: 7px 13px
  button-pill-selected:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.pill}"
  button-icon:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    size: 36px
  button-send:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.pill}"
    size: 36px
  provenance-chip:
    backgroundColor: "{colors.card-2}"
    textColor: "{colors.muted}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: 3px 10px
  user-bubble:
    backgroundColor: "{colors.card-2}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 10px 15px
  plan-block:
    backgroundColor: "{colors.card}"
    textColor: "{colors.muted}"
    typography: "{typography.label}"
    rounded: "{rounded.lg}"
    padding: 12px 14px
  artifact-card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.card}"
    padding: 12px 14px
  artifact-panel:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.shell}"
    padding: 18px 20px
  review-card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.body}"
    typography: "{typography.body}"
    rounded: "{rounded.card}"
    padding: 14px 16px
  diff-block:
    backgroundColor: "{colors.card-2}"
    textColor: "{colors.body}"
    typography: "{typography.mono}"
    rounded: "{rounded.sm}"
    padding: 8px 10px
  notice-warning:
    backgroundColor: "{colors.card}"
    textColor: "{colors.body}"
    typography: "{typography.body}"
    rounded: "{rounded.card}"
    padding: 14px 16px
  notice-denied:
    backgroundColor: "{colors.card}"
    textColor: "{colors.body}"
    typography: "{typography.body}"
    rounded: "{rounded.card}"
    padding: 14px 16px
  preset-card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.feature}"
    padding: 12px 14px
  inset-list:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 12px 16px
  command-palette:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.shell}"
    padding: 10px
    width: 560px
  toast:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.lg}"
    padding: 12px 14px
---

# Atlas Hybrid Glass: the ygg-atlas design standard

> **This file is the single source of truth for all ygg-atlas UI.** Every new screen, component,
> or visual change follows it. If something you need isn't here, add it here first, then build it.
> Technique (springs, gestures, materials) comes from `.claude/skills/apple-design/SKILL.md`.
> When the two disagree, **this file wins.**
> Live reference mockup: `docs/design/reference/atlas-hybrid-glass.html` (open in a browser, Mode ①).

## Overview

Atlas is a governed data-intelligence tool. People come to it to **trust a number** and **understand
why it moved**. The design serves that in four layers, each borrowed from a product that does it best:

| Layer | Borrowed from | What it gives Atlas |
|---|---|---|
| **Foundation: material & structure** | Apple (iOS/macOS 26 glass) | Floating translucent chrome over solid content; inset glass sidebar; scroll-edge blur; critically damped motion; press feedback; accessibility fallbacks |
| **Voice: palette, type, reading** | Claude | Cream canvas, warm ink, single clay accent, serif headings, soft blur-in streaming, "Worked for Ns" collapse, artifact side panel |
| **Agency: showing the work** | Codex | Live plan checklist with tool names, elapsed timer, send⇄stop, background jobs tray, thread status, review-diff before any action, mono ids |
| **Discovery: starting points** | Higgsfield | Preset gallery cards that preview their output on hover |
| **Trust: Atlas-native** | ygg-atlas guardrails | Provenance chip on every number, clarify instead of guess, denial stated as fact, freshness warnings |

**Key characteristics**
- Glass is a *floating functional layer*: sidebar, toolbar, composer, popovers, palette, toasts, briefing. Content (charts, tables, KPIs, answers) sits on **solid** cards or the canvas.
- One accent color, **clay** (`{colors.primary}`). It marks the primary action, focus, selection and data series. No second brand color.
- Serif for headings, sans for everything people *read quickly or compare*, tabular figures for every number.
- Motion says what happened and where things came from. It's never decoration.
- Every number shows where it came from.

## Colors

### Surfaces
- **Canvas** (`{colors.canvas}` #faf9f5, dark `{colors.canvas-dark}`) is the warm page floor. Never pure white. The canvas carries a faint warm **ambient wash** (two low-alpha radial gradients, clay and amber, top corners). It is static and is the only gradient in the system. It gives glass something to refract.
- **Card** (`{colors.card}`) is the solid surface for all data: KPI tiles, charts, tables, answers' metric cards, review cards, lists.
- **Card-2** (`{colors.card-2}`) is the recessed fill for user bubbles, provenance chips, diff blocks and skeletons.
- **Glass** (`{colors.glass}`, heavier `{colors.glass-heavy}` for the sidebar) is translucent chrome. Recipes are under *Elevation & Depth*.

### Text
- **Ink** (`{colors.ink}`) is for headings, numbers and emphasis. **Body** (`{colors.body}`) is running text. **Muted** (`{colors.muted}`) is for labels and metadata. **Muted-2** (`{colors.muted-2}`) is for placeholders and tertiary text.

### Accent & semantic
- **Primary / clay** (`{colors.primary}`, #b45536, AA 4.9:1 with white) is used for the primary button, send button, selected pill, focus ring (`{colors.primary-soft}` at 4px), links, chart series and progress.
- **Positive / Negative** (`{colors.positive}` / `{colors.negative}`) are used **only** for deltas, health states and diff add/remove. Never on buttons.
- **Warning** (`{colors.warning}`) is for staleness and caution notices.
- **Data series**: a single series uses the accent. For multiple series, use accent opacity steps (100/70/45/30%) before introducing new hues. Ask before adding a categorical palette.

### Dark mode
Every token has a `-dark` twin. Theme changes cross-fade over 450ms, with no flash. Filled controls keep `{colors.primary}` with white text. Text, links and chart lines on dark surfaces use `{colors.primary-on-dark}` (#d97a57, 5.7:1).

## Typography

- **Headings**: Source Serif 4, weight 400. `{typography.display}` is for page greetings and titles, `{typography.title}` for answer headings, `{typography.section}` for panel and toolbar titles. Serif headings are never bold.
- **Reading & UI**: Inter. `{typography.answer}` (15.5/1.65) is for assistant prose, `{typography.body}` for UI text, `{typography.label}` for buttons, pills and plan rows, `{typography.caption}` for chips and metadata.
- **Numbers**: `{typography.metric-xl}` / `{typography.metric-lg}` at weight 600 with negative tracking. **All numbers use tabular figures** (`font-variant-numeric: tabular-nums`), in tables and prose alike.
- **Mono**: JetBrains Mono for metric ids, tool names, scopes, diffs and elapsed timers. These are the Codex layer's "machine" voice.
- Tracking depends on size: tighter as text grows (`-0.01` to `-0.03em`), neutral for body, never positive except uppercase micro-labels.
- Fonts are self-hosted via `@fontsource-variable/inter`, `@fontsource-variable/source-serif-4` and `@fontsource-variable/jetbrains-mono`. No runtime font CDN.

## Layout

- **Shell**: a 10px inset (`{spacing.shell-gap}`). It holds the floating glass sidebar (236px, `{rounded.shell}`) and the main pane (`{rounded.shell}`). The artifact panel slides in on the right.
- **Floating chrome**: the toolbar sits 10px from the top and 14px from the sides. The composer sits 16px from the bottom, centered, max 740px. Content reserves `{spacing.chrome-clearance}` at the top and `{spacing.composer-clearance}` at the bottom so nothing hides under glass at rest.
- **Content widths**: dashboard ≤1080px, chat column ≤740px, catalog and settings ≤760px.
- **Grid**: 4px base. KPI row is 4 columns, then 2 under 1000px. Dashboard row 2 splits 1.6fr / 1fr. Presets are 4 columns, then 2.
- **Empty chat**: greeting and composer are vertically centered. On first send the composer glides to the bottom (shared-element motion).

## Elevation & Depth

| Level | Treatment | Used for |
|---|---|---|
| Canvas | `{colors.canvas}` + ambient wash | Page floor |
| Solid card | `{colors.card}`, 1px `{colors.hairline-soft}` ring, `0 1px 2px` shadow | All data |
| Lifted card | ring `{colors.hairline}` + `0 14px 34px rgba(0,0,0,.10)` | Hover on presets, artifact cards |
| Glass | see recipe | Floating chrome only |
| Panel | `{colors.card}` + `0 20px 60px rgba(0,0,0,.14)` | Artifact side panel |
| Scrim | `{colors.scrim}` | Behind modal tasks (⌘K) only |

**Glass recipe** (light / dark):
```css
background: var(--glass);                       /* {colors.glass} / {colors.glass-dark} */
backdrop-filter: saturate(180%) blur(22px);
border: 1px solid var(--glass-edge);            /* bright edge = light catching the material */
box-shadow: 0 1px 1px rgba(0,0,0,.04), 0 10px 30px rgba(0,0,0,.08),
            inset 0 1px 0 rgba(255,255,255,.95), inset 0 -1px 0 rgba(0,0,0,.03);
```
- **Specular highlight**: on the composer, toolbar, sidebar and briefing only, a soft radial highlight follows the pointer (`soft-light`, 180×100px). This is how Atlas mimics Liquid Glass reacting to light.
- **Scroll-edge effect**: where content scrolls under floating chrome, use a 6px blur masked to fade out. No hard 1px dividers under the toolbar.
- **Never glass on glass.** Never put charts, tables or KPI values on glass. The briefing card is the one glass content surface, and it holds narrative prose only.
- `prefers-reduced-transparency: reduce` turns all glass solid (`{colors.card}`) with no blur and no specular highlight.

## Shapes

| Token | Value | Use |
|---|---|---|
| `{rounded.sm}` | 8px | Diff blocks, inner chart bars |
| `{rounded.md}` | 12px | Nav items, palette rows, job rows |
| `{rounded.lg}` | 16px | Plan block, inset lists, toasts, user bubble |
| `{rounded.card}` | 18px | Every solid card |
| `{rounded.shell}` | 22px | Sidebar, main pane, artifact panel, palette |
| `{rounded.feature}` | 24px | Briefing, preset cards, popovers |
| `{rounded.glass}` | 26px | Toolbar, composer: the capsule chrome |
| `{rounded.pill}` | full | All buttons, pills, chips, icon buttons |

Bigger surfaces get bigger radii. Corners nest concentrically: inner radius = outer radius − padding.

## Components

### Shell & chrome (Apple)
- **`shell-sidebar`**: floating glass, inset. It holds the brand, nav (Overview, Ask Atlas, Metrics, …), and **threads** with Codex status: a pulsing accent dot for running threads and mono elapsed or last-run time.
- **`glass-toolbar`**: serif title on the left. On the right: the **jobs pill** ("◷ 2 running") and search/⌘K.
- **`glass-composer`**: textarea, then a row of pills (＋ Source), the elapsed timer (mono, only while working), and **`button-send`**. While streaming, send morphs into a stop square with a spinning progress ring. Focus shows a 4px `{colors.primary-soft}` ring.
- **`glass-popover`**: anchored to its trigger (transform-origin = trigger), enters with blur + scale + fade. Used for the jobs tray, provenance definitions and menus.
- **`command-palette`** (⌘K, `cmdk`): searches metrics, artifacts, threads and "Ask …". Opens with a scrim and blurs into place.
- **`toast`** (`sonner`): glass, bottom-right, stacking. Only for completions that happen *away* from the trigger (export ready, schedule saved).

### Answers (Claude + Codex)
- **`user-bubble`**: right-aligned, `{colors.card-2}`, tail corner 6px bottom-right.
- **`plan-block`**: Codex live plan. A checklist of steps, each with a status box (empty, then spinner, then ✓), the step text, and the **tool name in mono** on the right. The header shimmers while working. **When the answer finishes it collapses into "Worked for Ns · N steps"** (Claude), and expands again on click. This is the visible audit trail.
- **Answer prose**: `{typography.title}` heading, then `{typography.answer}` paragraphs streamed (see *Motion*). Bold marks the key figures.
- **`metric-card`**: the headline number of an answer. `{typography.metric-xl}`, a delta badge, and a digit roll on appear.
- **`provenance-chip`** (Atlas, **mandatory**): metric id, source (read-only), and a freshness dot (green, or amber when stale). It appears under every answer and on every KPI. Hovering it opens a glass popover with the vetted definition. Hovering a number in prose highlights its chip.
- **`artifact-card`**: an inline card linking to a chart or table. Click it and the **`artifact-panel`** slides in from the right and leaves the same way. It offers Export and Save to dashboard.
- **`review-card`**: Codex review-before-apply. Header "Proposed change · needs your approval", a **`diff-block`** (mono, `+` positive, `−` negative and struck through), then Approve / Edit / Dismiss. **Every agent action that writes, schedules or sends goes through this card.** Approve morphs to "✓ Approved", and the toast confirms.
- **Clarify** (Atlas, guardrail #1): when no governed metric matches, the assistant explains why it won't guess and offers **choice pills** for the metric and the period. It never invents a number.
- **`notice-denied`** (Atlas, guardrail #4): lock icon, "X isn't available to your role", why ("access comes from your sign-in"), which scope to request (mono), a provenance chip "scope · from your Google sign-in", and in-scope alternatives as pills.
- **`notice-warning`** (Atlas, guardrail #2): amber-tinted card, "Source last synced N hours ago", and a **Refresh source** pill that morphs: "↻ Refresh", then "Syncing…", then "✓ Synced". The answer's freshness chip turns amber.

### Dashboard
- **Greeting**: `{typography.display}` with a muted subline.
- **`briefing-card`**: a glass editorial summary of what changed and why, plus "Ask why →".
- **`kpi-card`**: label + delta, `{typography.metric-lg}` value with digit roll, provenance chip.
- **Chart card**: line draws in (1.3s), area fades in afterwards. Range change *morphs* the line, never redraws it.
- **Top-N table**: tabular figures, inline accent bars that grow in staggered by 60ms.
- **`preset-card`** (Higgsfield): a preview area plus title and description. Hover lifts the card 3px and **plays its preview** (line draws, bars grow). Click starts that analysis.
- **`inset-list`**: Apple grouped list for catalogs and settings. Serif group headers, rows expand on a spring to show the definition and freshness, and mono ids sit beside names.

### Feedback vocabulary
Status (spinner, shimmer, timer) → completion (✓ morph *in place*, toast only if out of view) → warning (amber notice) → error or denial (neutral notice that states the fact plus next steps). Validate inline, never on submit.

## Motion

Library: **`motion`** (springs, layout/shared-element, `AnimatePresence`). Numbers: **`@number-flow/react`**. Streaming markdown: **`streamdown`**. Page transitions: the native View Transitions API.

### Tokens
| Token | Value | Use |
|---|---|---|
| `ease-out` | `cubic-bezier(.22,1,.36,1)` | Default for CSS transitions |
| `ease-sheet` | `cubic-bezier(.32,.72,0,1)` | Panels, the composer glide |
| `spring-default` | `{ type:"spring", bounce:0, duration:0.35 }` | All interactive motion (critically damped) |
| `spring-momentum` | `{ bounce:0.2, duration:0.4 }` | Only after a physical flick or drag |
| `press` | `scale(.96–.97)`, 100ms ease-out, on pointer-down | Every button, pill, card, nav item |
| `micro` | 200ms | Hover color, opacity |
| `standard` | 350–450ms | Popovers, cards appearing, collapses |
| `panel` | 550–650ms | Artifact panel, composer glide |

### Rules
1. **Respond on press.** Feedback starts on pointer-down. Never add artificial delays.
2. **Everything interactive can be interrupted.** Use springs from the current value. CSS keyframes are only for passive, looping or decorative states (shimmer, spinner, draw-in).
3. **Same path in and out.** The artifact panel enters from the right and leaves to the right. Popovers grow from their trigger.
4. **Materialize glass.** Glass surfaces enter with opacity, scale (.92–.96 → 1) and blur (6–8px → 0) together.
5. **No bounce** except after momentum gestures. No looping motion except status indicators.

### Streaming (the core of the chat experience)
- **Adaptive pacing**: buffer incoming tokens and release them on a ~40ms tick, 1 word per tick normally, 2 when the backlog is over 5, 3 when it's over 12. Text flows evenly and never falls far behind the network.
- **Reveal**: each released word chunk fades in from `blur(3px)` to sharp over 420ms. **Text already on screen never re-animates or reflows.**
- **Incomplete markdown** is held back until it closes (`streamdown`, replacing the bespoke `markdown-stream.ts`). Only the last block re-renders.
- **Caret**: a small pulsing accent dot after the last token. It's removed at the end.
- **Auto-scroll** happens only while the user is within 240px of the bottom. Scrolling up pauses it.
- **Order of appearance**: plan → heading → metric card (digit roll) → prose → artifact card → provenance chips (90ms stagger) → actions.
- **Code and terminal blocks** may use a per-character typewriter. Prose never does.

### Accessibility
- `prefers-reduced-motion`: cross-fades replace slides, springs and blur. Digits set instantly. Streaming shows chunks without blur.
- `prefers-reduced-transparency`: all glass becomes solid.
- `prefers-contrast: more`: solid backgrounds and a 1px `{colors.ink}` border on chrome.
- Minimum hit target 36px (44px on touch). Focus is always visible (`{colors.primary-soft}` ring). Color is never the only signal: deltas carry ▲/▼ and states carry text.

## Do's and Don'ts

### Do
- Put glass **only** on floating chrome. Keep data on solid cards.
- Show provenance on **every** number, and say "I don't know which metric" before ever guessing.
- Route every write, schedule or send action through a `review-card` diff.
- Use tabular figures everywhere numbers appear.
- Collapse the plan into "Worked for Ns" when done, and keep it expandable.
- Animate from where things are, toward where they came from.
- Reuse tokens. Add new ones to this file before using them.

### Don't
- Don't stack glass on glass or put charts or tables on glass.
- Don't add a second accent, per-source brand colors, or decorative gradients (the ambient wash is the only one).
- Don't bold serif headings or set body text in serif.
- Don't use bounce on menus or fades, or scroll-jacking, parallax, 3D tilt, confetti, or animated backgrounds.
- Don't show a toast for something the user can already see change in place.
- Don't hide a stale-data warning or a denial. State it plainly with a next step.
- Don't import fonts from a CDN at runtime.

## Responsive Behavior

| Width | Changes |
|---|---|
| ≥ 1200px | Full shell; artifact panel opens beside chat (min(44vw, 540px)) |
| 1000–1199px | Artifact panel overlays chat as a sheet with scrim |
| < 1000px | Sidebar hidden behind toolbar menu; KPIs and presets go to 2 columns; dashboard row 2 stacks |
| < 640px | Composer full-width, 12px from edges; panels become bottom sheets (`vaul`, later) with momentum springs |

## Origin map (for reviewers)

| Element | Origin |
|---|---|
| Floating glass sidebar, toolbar, composer, popovers, palette, toasts; scroll-edge blur; specular highlight; press scale; inset grouped list; suggestion pills; digit roll | Apple |
| Cream/clay palette, serif headings, blur-in streaming, "Worked for Ns" collapse, artifact card + side panel, briefing card, centered empty-state composer | Claude |
| Live plan with tool names, elapsed timer, send⇄stop + ring, jobs tray, thread status dots, review diff before apply, mono ids | Codex |
| Preset gallery with hover-play previews | Higgsfield |
| Provenance chips + definition popover, number↔chip linking, clarify pills, denial notice, freshness warning | Atlas |

## Iteration Guide

1. Before building UI, read this file and the reference mockup (`docs/design/reference/atlas-hybrid-glass.html`, Mode ①).
2. Use tokens (`{colors.*}`, `{typography.*}`, `{rounded.*}`, `{spacing.*}`) through the CSS variables in `frontend/src/index.css`. Never hard-code hex values in components.
3. A new component starts as a `components:` entry and a *Components* paragraph here, in the same PR.
4. Motion uses the motion tokens and the shared presets module, never ad-hoc durations.
5. Check every screen in light, dark, reduced-motion and reduced-transparency before merge.
6. Lint after editing: `npx @google/design.md lint DESIGN.md`.

## Known Gaps

- The categorical chart palette for more than four series is undefined. Use accent opacity steps until one is designed.
- Mobile bottom sheets (`vaul`) and the gesture rules (velocity handoff, rubber-banding) are deferred until there's a mobile surface.
- Source Serif 4 and Inter substitute for Claude's licensed faces. Don't reference Anthropic's fonts or mark.

# Atlas Hybrid Glass: implementation overview (parallel tracks)

> **For agentic workers:** this is the index. Each track has its own plan, executed with
> superpowers:subagent-driven-development in its own git worktree (superpowers:using-git-worktrees).
> Spec: `docs/specs/2026-10-08-atlas-hybrid-glass-design.md` · Standard: `DESIGN.md`.

**Goal:** Ship the Atlas Hybrid Glass UI standard across the app (spec Phases 1–3), parallelising
independent work across isolated tracks.

## Tracks, dependencies and waves

| Plan | Track | Area | Depends on |
|---|---|---|---|
| `…-01-foundation.md` | **A** | Frontend tokens, fonts, `ui/` primitives, glass shell, routing | none |
| `…-02-backend-structured-answers.md` | **C** | `clarify` + `artifact` answer blocks, persistence, prompt, goldens | none |
| `…-03-backend-read-endpoints.md` | **E-be** | `GET /api/v1/atlas/metrics`, `GET /api/v1/atlas/overview` | none |
| `…-04-chat-experience.md` | **B** | Chat restyle, streamdown streaming, steps block, composer, notices, provenance popover | A |
| `…-05-catalog-and-command.md` | **D1** | Metrics catalog page, ⌘K palette | A, E-be (contract only) |
| `…-06-dashboard.md` | **E-fe** | Overview dashboard (briefing-free), KPI cards, top-N, presets | A, E-be (contract only) |
| `…-07-answer-blocks-ui.md` | **D2** | Clarify pills, artifact card + side panel | B, C (contract only) |

```
Wave 1 (parallel):  A ─────────┐   C ───────────────┐   E-be ──────┐
Wave 2 (parallel):  B ◄── A      D1 ◄── A           E-fe ◄── A
Wave 3:             D2 ◄── B (+ C contract)
Integration:        merge order A → C → E-be → B → D1 → E-fe → D2, full test + lint after each
```

Frontend tracks in the same wave touch **disjoint folders** (`features/chat` vs `features/metrics` +
`features/command` vs `features/dashboard`). The only shared files are `App.tsx` (one route line each)
and `api/` (new files each). Resolve those trivially at merge.

## Out of scope (deferred, needs capability that doesn't exist)
- **Jobs tray / background threads**: no background job runner exists.
- **Review card (diff before apply)**: the agent has no write/schedule/send actions. Each future action
  needs its own guardrail spec first (guardrail #3 read-only connectors).
- **AI briefing card**: an LLM summary needs its own eval coverage. Goes in a later plan.
- **`plan` SSE event**: the steps block is derived from `tool_status` (YAGNI, same UX).

## Shared contracts (all tracks code against these, verbatim)

### 1. Answer blocks (Track C produces, Track D2 consumes)

`done` SSE event and persisted `ChatMessage` gain `blocks`:

```ts
// frontend/src/api/chat.ts (Track C adds these types; D2 consumes)
export interface ClarifyOption { label: string; metric_id?: string | null }
export interface ClarifyBlock { kind: 'clarify'; question: string; options: ClarifyOption[] }
export interface ArtifactBlock {
  kind: 'artifact';
  id: string;                                   // e.g. "metric_breakdown:revenue:1"
  artifact_type: 'breakdown' | 'comparison' | 'funnel';
  title: string;
  unit: string;                                 // '' when unitless
  columns: string[];
  rows: (string | number | null)[][];
  provenance: Provenance;
}
export type AnswerBlock = ClarifyBlock | ArtifactBlock;
// ChatMessage.blocks?: AnswerBlock[] | null
// ChatStreamEvent 'done' gains: blocks?: AnswerBlock[]; message_id?: string
```

```python
# backend: done event
{"type": "done", "content": str, "provenance": list[dict], "blocks": list[dict], "model": str,
 "token_usage": dict, "message_id": str}
```

### 2. Read endpoints (Track E-be produces, D1 + E-fe consume)

```ts
// GET /api/v1/atlas/metrics
export interface CatalogMetric { id: string; name: string; description: string; unit: string;
  time_scope: 'range' | 'snapshot'; has_breakdown: boolean; entity: string }
export interface CatalogFunnel { id: string; name: string; description: string; entity: string }
export interface CatalogSource { id: string; name: string; description: string;
  metrics: CatalogMetric[]; funnels: CatalogFunnel[] }
export interface MetricsCatalog { sources: CatalogSource[] }

// GET /api/v1/atlas/overview?days=30   (days ∈ 7 | 30 | 90, default 30)
export interface OverviewKpi { metric_id: string; name: string; unit: string;
  value: number; previous: number | null; delta_pct: number | null;
  good_direction: 'up' | 'down'; provenance: Provenance }
export interface OverviewBreakdown { metric_id: string; name: string; unit: string;
  rows: { label: string; value: number }[]; provenance: Provenance }
export interface Overview { days: number; start_date: string; end_date: string;
  kpis: OverviewKpi[]; breakdown: OverviewBreakdown | null }
```
Both endpoints run through `AtlasTools.execute` with `surface="api"` so every call is audited (guardrail #5).

## Merge & verification gate (every track)
- Frontend: `cd frontend && corepack pnpm test && corepack pnpm lint && corepack pnpm typecheck`
- Backend: `cd backend && uv run pytest --cov=app && uv run ruff check . && uv run ruff format --check .`
- DESIGN.md touched → `npx @google/design.md lint DESIGN.md` (0 errors)
- UI tracks: run the app (`run` skill) and check light, dark, reduced-motion and reduced-transparency against
  `docs/design/reference/atlas-hybrid-glass.html` Mode ①.
- Commits: `<type>(<scope>): <description>`; branch per track `feature/hybrid-glass-<track>`.

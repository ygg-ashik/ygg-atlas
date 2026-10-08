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

/** Business-language label for a tool; unknown tools fall back to their id. */
export function stepLabel(tool: string): string {
  return LABELS[tool] ?? tool;
}

/** A new tool_status completes the running step and starts itself. */
export function applyToolStatus(steps: Step[], tool: string): Step[] {
  return [...completeAll(steps), { tool, status: 'running' }];
}

export function completeAll(steps: Step[]): Step[] {
  return steps.map((s) => (s.status === 'done' ? s : { ...s, status: 'done' }));
}

/** Completed steps for a persisted answer: one per distinct tool + metric. */
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

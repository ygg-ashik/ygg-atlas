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
    expect(completeAll([{ tool: 'a', status: 'running' }])).toEqual([
      { tool: 'a', status: 'done' },
    ]);
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

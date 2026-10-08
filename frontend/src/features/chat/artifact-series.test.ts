import { describe, expect, it } from 'vitest';
import { seriesFor } from './artifact-series';
import type { ArtifactBlock } from '@/api/chat';

const base = {
  kind: 'artifact',
  id: 'x',
  title: 't',
  unit: 'AED',
  provenance: { tool: 't', source: 's', executed_at: 'e' },
} as const;

describe('seriesFor', () => {
  it('breakdown: label + value', () => {
    const a: ArtifactBlock = {
      ...base,
      artifact_type: 'breakdown',
      columns: ['Label', 'Value'],
      rows: [
        ['b2b', 1000],
        ['b2c', 500],
      ],
    };
    expect(seriesFor(a)).toEqual([
      { label: 'b2b', value: 1000 },
      { label: 'b2c', value: 500 },
    ]);
  });
  it('comparison: period + value column', () => {
    const a: ArtifactBlock = {
      ...base,
      artifact_type: 'comparison',
      columns: ['Period', 'Start', 'End', 'Value'],
      rows: [
        ['A', '2026-09-01', '2026-09-30', 120],
        ['B', '2026-08-01', '2026-08-31', 100],
      ],
    };
    expect(seriesFor(a)).toEqual([
      { label: 'A · 2026-09-01 → 2026-09-30', value: 120 },
      { label: 'B · 2026-08-01 → 2026-08-31', value: 100 },
    ]);
  });
  it('funnel: step + users; non-numeric values are dropped', () => {
    const a: ArtifactBlock = {
      ...base,
      artifact_type: 'funnel',
      columns: ['Step', 'Users', 'Conversion from previous %'],
      rows: [
        ['View', 100, null],
        ['Cart', 60, 60],
        ['Bad', null, null],
      ],
    };
    expect(seriesFor(a)).toEqual([
      { label: 'View', value: 100 },
      { label: 'Cart', value: 60 },
    ]);
  });
});

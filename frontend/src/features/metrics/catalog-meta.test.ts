import { describe, expect, it } from 'vitest';
import { metricMeta } from './catalog-meta';

describe('metricMeta', () => {
  it('describes a range metric with unit and breakdown', () => {
    expect(metricMeta({ time_scope: 'range', unit: 'AED', has_breakdown: true })).toBe(
      'Range (needs dates) · AED · has breakdown',
    );
  });
  it('omits an empty unit and missing breakdown', () => {
    expect(metricMeta({ time_scope: 'snapshot', unit: '', has_breakdown: false })).toBe(
      'Snapshot (as of now)',
    );
  });
});

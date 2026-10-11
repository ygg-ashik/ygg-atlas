import { describe, expect, it } from 'vitest';
import type { Provenance } from '@/api/chat';
import { maskingLabel, maskingNote, policyLabels, scopeLabel } from './provenance-policy';

const base: Provenance = {
  tool: 'metric_breakdown',
  source: 'deepsales',
  executed_at: '2026-10-10T00:00:00Z',
};

describe('scopeLabel', () => {
  it('names the scope dimensions of a restricted result', () => {
    expect(scopeLabel({ restricted: true, dimensions: ['csm', 'region'] })).toBe(
      'rows · scoped to csm, region',
    );
  });

  it('still says rows are scoped when no dimension is named', () => {
    expect(scopeLabel({ restricted: true, dimensions: [] })).toBe('rows · scoped');
  });

  it('is absent for an unrestricted or missing scope', () => {
    expect(scopeLabel({ restricted: false, dimensions: [] })).toBeNull();
    expect(scopeLabel(null)).toBeNull();
    expect(scopeLabel(undefined)).toBeNull();
  });
});

describe('maskingLabel', () => {
  it.each([
    ['business_name', 'pseudonymise', 'account names · pseudonymised'],
    ['person_name', 'suppress', 'people names · suppressed'],
    ['business_name', 'bucket', 'account names · bucketed'],
  ])('describes %s masked by %s', (labelClass, mode, expected) => {
    expect(maskingLabel({ label_class: labelClass, mode })).toBe(expected);
  });

  it('falls back to generic wording for an unknown class or mode', () => {
    expect(maskingLabel({ label_class: 'other', mode: 'redact' })).toBe('names · redact');
  });

  it('is absent when nothing was masked', () => {
    expect(maskingLabel(null)).toBeNull();
    expect(maskingLabel(undefined)).toBeNull();
  });
});

describe('policyLabels', () => {
  it('lists scope and masking, deduplicated across provenance records', () => {
    const scoped: Provenance = {
      ...base,
      scope: { restricted: true, dimensions: ['csm'] },
      masking: { label_class: 'business_name', mode: 'suppress' },
    };
    expect(policyLabels([scoped, { ...scoped, metric_id: 'other' }])).toEqual([
      'rows · scoped to csm',
      'account names · suppressed',
    ]);
  });

  it('is empty for unscoped, unmasked provenance', () => {
    expect(policyLabels([base, { ...base, scope: { restricted: false, dimensions: [] } }])).toEqual(
      [],
    );
  });
});

describe('maskingNote', () => {
  it('counts hidden rows, singular and plural', () => {
    expect(maskingNote({ suppressed_rows: 4 })).toBe('4 rows hidden by name masking');
    expect(maskingNote({ suppressed_rows: 1 })).toBe('1 row hidden by name masking');
  });

  it('states what the Others row covers', () => {
    expect(maskingNote({ others_covers: 'remaining fetched rows' })).toBe(
      'Others = remaining fetched rows',
    );
  });

  it('is absent when nothing was masked', () => {
    expect(maskingNote({})).toBeNull();
    expect(maskingNote({ suppressed_rows: null, others_covers: null })).toBeNull();
  });
});

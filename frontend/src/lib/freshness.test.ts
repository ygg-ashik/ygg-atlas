// src/lib/freshness.test.ts
import { describe, expect, it } from 'vitest';
import { freshnessLabel, isStale, parseFreshness } from './freshness';

const NOW = new Date('2026-10-08T12:00:00Z');

describe('freshness', () => {
  it('parses ISO and Postgres-style timestamps', () => {
    expect(parseFreshness('2026-10-08T10:00:00+00:00')?.toISOString()).toBe(
      '2026-10-08T10:00:00.000Z',
    );
    expect(parseFreshness('2026-10-08 10:00:00+00:00')?.toISOString()).toBe(
      '2026-10-08T10:00:00.000Z',
    );
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

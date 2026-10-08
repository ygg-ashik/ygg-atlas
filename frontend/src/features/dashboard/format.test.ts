import { describe, expect, it } from 'vitest';
import { deltaLabel, deltaTone, formatKpi, numberFormat } from './format';

describe('dashboard format', () => {
  it('formats AED compactly as currency', () => {
    expect(formatKpi(4_820_000, 'AED')).toMatch(/AED\s?4\.82M/);
  });
  it('formats counts with grouping, compact above 100k', () => {
    expect(formatKpi(38214, 'orders')).toBe('38,214');
    expect(formatKpi(1_250_000, '')).toBe('1.3M');
  });
  it('keeps percent units', () => {
    expect(formatKpi(12.345, '%')).toBe('12.3%');
  });
  it('numberFormat is the Intl options NumberFlow receives', () => {
    expect(numberFormat('AED', 5)).toMatchObject({ style: 'currency', currency: 'AED' });
  });
  it('tone respects the metric direction', () => {
    expect(deltaTone(5, 'up')).toBe('positive');
    expect(deltaTone(5, 'down')).toBe('negative');
    expect(deltaTone(-2, 'down')).toBe('positive');
    expect(deltaTone(0, 'up')).toBe('neutral');
    expect(deltaTone(null, 'up')).toBe('neutral');
  });
  it('labels deltas with an arrow (color is never the only signal)', () => {
    expect(deltaLabel(12.4)).toBe('▲ 12.4%');
    expect(deltaLabel(-2.3)).toBe('▼ 2.3%');
    expect(deltaLabel(null)).toBe('');
  });
});

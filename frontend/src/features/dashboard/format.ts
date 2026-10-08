// Pure KPI formatting and delta-tone rules for the Overview dashboard.
import type { Format } from '@number-flow/react';

const COMPACT_ABOVE = 100_000;

/** Intl options per unit; also the `format` prop NumberFlow receives so the roll matches the text. */
export function numberFormat(unit: string, value: number): Format {
  if (unit === 'AED') {
    return {
      style: 'currency',
      currency: 'AED',
      notation: 'compact',
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    };
  }
  if (unit === '%') return { maximumFractionDigits: 1 };
  if (Math.abs(value) >= COMPACT_ABOVE) return { notation: 'compact', maximumFractionDigits: 1 };
  return { maximumFractionDigits: 1 };
}

export function formatKpi(value: number, unit: string): string {
  const text = new Intl.NumberFormat('en-US', numberFormat(unit, value)).format(value);
  return unit === '%' ? `${text}%` : text;
}

export type Tone = 'positive' | 'negative' | 'neutral';

/** Direction-aware: a rise is good only when the metric's good direction is up. */
export function deltaTone(deltaPct: number | null, good: 'up' | 'down'): Tone {
  if (deltaPct === null || deltaPct === 0) return 'neutral';
  const rising = deltaPct > 0;
  return rising === (good === 'up') ? 'positive' : 'negative';
}

/** Arrow + magnitude, so color is never the only signal. No change has no arrow
 * (its tone is neutral, so there is no direction to signal). */
export function deltaLabel(deltaPct: number | null): string {
  if (deltaPct === null) return '';
  if (deltaPct === 0) return '0.0%';
  return `${deltaPct >= 0 ? '▲' : '▼'} ${Math.abs(deltaPct).toFixed(1)}%`;
}

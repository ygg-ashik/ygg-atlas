import NumberFlow from '@number-flow/react';
import type { OverviewKpi } from '@/api/overview';
import { freshnessLabel, isStale } from '@/lib/freshness';
import { cn } from '@/ui';
import { deltaLabel, deltaTone, formatKpi, numberFormat } from '../format';

const TONE = {
  positive: 'bg-positive/[0.12] text-positive',
  negative: 'bg-negative/[0.12] text-negative',
  neutral: 'bg-foreground/5 text-muted-foreground',
} as const;

/** DESIGN.md › kpi-card: solid card, digit roll, toned delta, provenance chip. */
export function KpiCard({ kpi }: { kpi: OverviewKpi }) {
  const tone = deltaTone(kpi.delta_pct, kpi.good_direction);
  return (
    <div className="rounded-card bg-card px-4 py-3.5 shadow-[0_0_0_1px_hsl(var(--border)/0.6),0_1px_2px_rgba(0,0,0,0.04)]">
      <div className="flex items-center justify-between gap-2 text-label text-muted-foreground">
        <span className="truncate">{kpi.name}</span>
        {kpi.delta_pct !== null && (
          <span
            data-tone={tone}
            className={cn(
              'shrink-0 rounded-full px-[7px] py-0.5 text-caption font-semibold',
              TONE[tone],
            )}
          >
            {deltaLabel(kpi.delta_pct)}
          </span>
        )}
      </div>
      <div
        role="img"
        aria-label={formatKpi(kpi.value, kpi.unit)}
        className="tabular my-2 text-metric-lg font-semibold text-ink"
      >
        <NumberFlow
          value={kpi.value}
          format={numberFormat(kpi.unit, kpi.value)}
          locales="en-US"
          suffix={kpi.unit === '%' ? '%' : undefined}
          aria-hidden
        />
      </div>
      <SourceChip source={kpi.provenance.source} freshness={kpi.provenance.freshness} />
    </div>
  );
}

/** Provenance chip: source plus data age; amber once the source is past its SLA. */
function SourceChip({ source, freshness }: { source: string; freshness?: string }) {
  const stale = isStale(freshness);
  return (
    <span
      data-stale={stale}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-card-2 px-2.5 py-[3px] text-caption text-muted-foreground',
        stale && 'border-warning/40 text-warning',
      )}
    >
      <span
        aria-hidden
        className={cn('h-1.5 w-1.5 rounded-full', stale ? 'bg-warning' : 'bg-positive')}
      />
      {source}
      {freshness && ` · ${freshnessLabel(freshness)}`}
    </span>
  );
}

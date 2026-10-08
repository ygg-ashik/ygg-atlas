import type { Provenance } from '@/api/chat';
import { freshnessLabel, isStale } from '@/lib/freshness';
import { cn } from '@/ui';

/** Provenance chip (guardrail 2): source plus data age; amber once the source is past its SLA. */
export function SourceChip({ provenance }: { provenance: Provenance }) {
  const { source, freshness, metric_id: metricId } = provenance;
  const stale = isStale(freshness);
  return (
    <span
      data-stale={stale}
      title={metricId ? `Metric: ${metricId}` : undefined}
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

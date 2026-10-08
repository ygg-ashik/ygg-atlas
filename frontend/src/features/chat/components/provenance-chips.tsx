import type { Provenance } from '@/api/chat';
import { freshnessLabel, isStale } from '@/lib/freshness';
import { formatDateTime } from '@/lib/utils';
import { cn, Popover, PopoverContent, PopoverTrigger } from '@/ui';

interface ProvenanceChipsProps {
  provenance: Provenance[];
}

const chipKey = (p: Provenance) => `${p.metric_id ?? p.tool}::${p.source}`;

/** The governed definition behind a chip, shown in a glass popover. */
function ProvenanceDefinition({ p }: { p: Provenance }) {
  return (
    <PopoverContent className="space-y-1">
      <p className="font-serif text-section text-ink">{p.metric_name ?? p.tool}</p>
      {p.metric_id && (
        <p>
          metric <code className="font-mono text-[11.5px]">{p.metric_id}</code>
        </p>
      )}
      <p>
        source <span className="text-ink">{p.source}</span> (read-only) · tool{' '}
        <code className="font-mono text-[11.5px]">{p.tool}</code>
      </p>
      {p.freshness && <p>data as of {freshnessLabel(p.freshness)}</p>}
      <p className="text-muted-foreground">executed {formatDateTime(p.executed_at)}</p>
    </PopoverContent>
  );
}

function ProvenanceChip({ p }: { p: Provenance }) {
  const stale = isStale(p.freshness);
  return (
    <Popover>
      <PopoverTrigger
        data-stale={stale}
        className={cn(
          'inline-flex max-w-full items-center gap-1.5 rounded-full border border-border/60 bg-card-2 py-[3px] pl-2 pr-2.5 text-caption text-muted-foreground transition-[color,transform] duration-200 hover:text-ink focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/15 active:scale-[.97]',
          stale && 'border-warning/40 text-warning',
        )}
      >
        <span
          aria-hidden
          className={cn('h-1.5 w-1.5 shrink-0 rounded-full', stale ? 'bg-warning' : 'bg-positive')}
        />
        <span className="truncate font-medium text-ink/90">{p.metric_name ?? p.tool}</span>
        <span className="text-muted-2">·</span>
        <span className="truncate">{p.source}</span>
        {p.freshness && (
          <>
            <span className="text-muted-2">·</span>
            <span className="shrink-0">{freshnessLabel(p.freshness)}</span>
          </>
        )}
        {stale && <span className="sr-only">(stale data)</span>}
      </PopoverTrigger>
      <ProvenanceDefinition p={p} />
    </Popover>
  );
}

/** Every number traces to one of these (guardrail #2). Built from the tool audit,
 * never LLM output. Click a chip to see the governed definition (glass popover). */
export function ProvenanceChips({ provenance }: ProvenanceChipsProps) {
  // Dedupe repeated executions of the same metric against the same source.
  const chips = Array.from(new Map(provenance.map((p) => [chipKey(p), p])).values());
  if (chips.length === 0) return null;

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5" aria-label="Data provenance">
      {chips.map((p) => (
        <ProvenanceChip key={chipKey(p)} p={p} />
      ))}
    </div>
  );
}

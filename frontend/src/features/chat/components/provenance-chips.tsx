import { Clock3, Database } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/ui';
import type { Provenance } from '@/api/chat';
import { formatDateTime } from '@/lib/utils';

interface ProvenanceChipsProps {
  provenance: Provenance[];
}

/**
 * Honest citation chips derived from the atlas tool-execution audit — never
 * from LLM output. Every number in an answer traces back to one of these:
 * metric (or tool), source system, and data freshness, with the execution
 * timestamp in the tooltip.
 */
export function ProvenanceChips({ provenance }: ProvenanceChipsProps) {
  // Dedupe repeated executions of the same metric against the same source.
  const chips = Array.from(
    new Map(provenance.map((p) => [`${p.metric_id ?? p.tool}::${p.source}`, p])).values(),
  );
  if (chips.length === 0) return null;

  return (
    <TooltipProvider delayDuration={150}>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5" aria-label="Data provenance">
        {chips.map((p) => (
          <Tooltip key={`${p.metric_id ?? p.tool}::${p.source}`}>
            <TooltipTrigger asChild>
              <span className="inline-flex max-w-full cursor-default items-center gap-1.5 rounded-full border bg-card py-0.5 pl-2 pr-2.5 text-[11px] leading-5 text-muted-foreground shadow-sm transition-colors hover:border-primary/40 hover:text-foreground">
                <Database className="h-3 w-3 shrink-0 text-primary" />
                <span className="truncate font-medium text-foreground/90">
                  {p.metric_name ?? p.tool}
                </span>
                <span className="text-muted-foreground/60">·</span>
                <span className="truncate">{p.source}</span>
                {p.freshness && (
                  <>
                    <span className="text-muted-foreground/60">·</span>
                    <span className="inline-flex shrink-0 items-center gap-0.5 text-accent-foreground">
                      <Clock3 className="h-2.5 w-2.5" />
                      {p.freshness}
                    </span>
                  </>
                )}
              </span>
            </TooltipTrigger>
            <TooltipContent side="bottom" align="start">
              <div className="space-y-0.5">
                <p className="font-medium">{p.metric_name ?? p.tool}</p>
                {p.metric_id && (
                  <p className="text-muted-foreground">
                    metric: <code>{p.metric_id}</code>
                  </p>
                )}
                <p className="text-muted-foreground">
                  tool: <code>{p.tool}</code>
                </p>
                <p className="text-muted-foreground">executed {formatDateTime(p.executed_at)}</p>
              </div>
            </TooltipContent>
          </Tooltip>
        ))}
      </div>
    </TooltipProvider>
  );
}

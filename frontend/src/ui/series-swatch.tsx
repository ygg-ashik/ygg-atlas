// src/ui/series-swatch.tsx
import type * as React from 'react';
import { cn } from './utils';

export type Series = 'primary' | 'secondary';

/** Fill classes for a bar of the given series. The second series keeps the accent
 * hue at 45% with a diagonal hatch (DESIGN.md › series-hatch). */
export function seriesFill(series: Series): string {
  return cn('bg-primary-text', series === 'secondary' && 'series-hatch');
}

/** Legend entry: a swatch in the series' pattern plus its label. */
export function SeriesSwatch({ series, children }: { series: Series; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <i
        aria-hidden
        data-series={series}
        className={cn('h-2.5 w-3.5 rounded-[3px]', seriesFill(series))}
      />
      {children}
    </span>
  );
}

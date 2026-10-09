// src/ui/future-control.tsx
import type * as React from 'react';
import { Lock } from 'lucide-react';
import { cn } from './utils';

export interface FutureControlProps {
  label: React.ReactNode;
  /** The dependency it waits for. */
  note?: React.ReactNode;
  /** A preview of the control; rendered inert (not focusable, not clickable). */
  children: React.ReactNode;
  className?: string;
}

/** A designed control the backend doesn't serve yet: visible, disabled, inert
 * (DESIGN.md › future-control). Never hidden, never interactive. */
export function FutureControl({
  label,
  note = 'Arrives with row and field controls',
  children,
  className,
}: FutureControlProps) {
  return (
    <div
      aria-disabled="true"
      className={cn(
        'rounded-md border border-dashed border-border bg-card-2 px-3.5 py-3',
        className,
      )}
    >
      <div className="mb-1.5 text-label font-medium text-ink">{label}</div>
      <div
        inert
        data-future-preview
        className="pointer-events-none flex flex-wrap gap-1.5 opacity-45 grayscale-[.4]"
      >
        {children}
      </div>
      <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
        <Lock aria-hidden className="h-[11px] w-[11px]" />
        {note}
      </p>
    </div>
  );
}

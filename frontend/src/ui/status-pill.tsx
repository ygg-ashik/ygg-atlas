// src/ui/status-pill.tsx
import type * as React from 'react';
import { cn } from './utils';

export type StatusTone = 'positive' | 'negative' | 'warning' | 'accent' | 'muted';

const TONE: Record<StatusTone, string> = {
  positive: 'bg-positive/10 text-positive',
  negative: 'bg-negative/10 text-negative',
  warning: 'bg-warning/10 text-warning',
  accent: 'bg-primary/10 text-primary-text',
  muted: 'bg-foreground/5 text-muted-foreground',
};

export interface StatusPillProps {
  tone?: StatusTone;
  /** A diamond dot marks a deny, so it reads without colour. */
  diamond?: boolean;
  children: React.ReactNode;
  className?: string;
}

/** Status as dot + text, never colour alone (DESIGN.md › status-pill). */
export function StatusPill({
  tone = 'muted',
  diamond = false,
  children,
  className,
}: StatusPillProps) {
  return (
    <span
      data-tone={tone}
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full py-0.5 pl-2 pr-[9px] text-xs font-medium leading-normal',
        TONE[tone],
        className,
      )}
    >
      <i
        aria-hidden
        data-dot={diamond ? 'diamond' : 'round'}
        className={cn(
          'h-1.5 w-1.5 shrink-0 bg-current',
          diamond ? 'rotate-45 rounded-[1px]' : 'rounded-full',
        )}
      />
      {children}
    </span>
  );
}

/** Group standing: the status pill in the accent (manager) or muted (member) tone. */
export function StandingPill({ standing }: { standing: 'manager' | 'member' }) {
  return <StatusPill tone={standing === 'manager' ? 'accent' : 'muted'}>{standing}</StatusPill>;
}

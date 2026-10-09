// src/ui/tag.tsx
import type * as React from 'react';
import { cn } from './utils';

export interface TagProps {
  children: React.ReactNode;
  /** Mono for ids, paths and origins. */
  mono?: boolean;
  /** A freshness dot, for provenance-style chips ("scope · from your Google sign-in"). */
  dot?: boolean;
  className?: string;
}

/** Neutral, non-interactive metadata chip (DESIGN.md › tag-chip). */
export function Tag({ children, mono = false, dot = false, className }: TagProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-border/50 bg-card-2 px-[9px] py-0.5 text-caption text-muted-foreground',
        mono && 'font-mono text-[11px]',
        className,
      )}
    >
      {dot && <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-positive" />}
      {children}
    </span>
  );
}

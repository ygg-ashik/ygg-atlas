// src/ui/empty-state.tsx
import type * as React from 'react';
import { cn } from './utils';

export interface EmptyStateProps {
  icon: React.ReactNode;
  title: React.ReactNode;
  children?: React.ReactNode;
  /** One action, centred (a filtered-empty list offers "Clear filters"). */
  actions?: React.ReactNode;
  className?: string;
}

/** Editorial empty state on a solid card (DESIGN.md › empty-state). */
export function EmptyState({ icon, title, children, actions, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'rounded-card bg-card px-6 pb-10 pt-11 text-center shadow-[0_0_0_1px_hsl(var(--border)/0.6),0_1px_2px_rgba(0,0,0,0.04)]',
        className,
      )}
    >
      <div
        aria-hidden
        className="mx-auto mb-3.5 grid h-[52px] w-[52px] place-items-center rounded-full bg-primary/10 text-primary-text"
      >
        {icon}
      </div>
      <h3 className="mb-1.5 font-serif text-title text-ink">{title}</h3>
      {children && (
        <p className="mx-auto mb-[18px] max-w-[440px] text-[14.5px] text-muted-foreground">
          {children}
        </p>
      )}
      {actions && <div className="flex flex-wrap justify-center gap-2.5">{actions}</div>}
    </div>
  );
}

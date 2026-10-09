// src/ui/notice.tsx
import type * as React from 'react';
import { cn } from './utils';

export interface NoticeProps {
  /** neutral: denials and errors stated as fact · warning: amber caution ("Shown once"). */
  tone?: 'neutral' | 'warning';
  icon: React.ReactNode;
  title?: React.ReactNode;
  children?: React.ReactNode;
  /** Right-aligned action (e.g. a Retry pill). */
  action?: React.ReactNode;
  role?: 'status' | 'alert';
  className?: string;
}

/** Notice card (DESIGN.md › notice-denied / notice-warning / notice-error):
 * a fact plus a next step, never hidden. */
export function Notice({
  tone = 'neutral',
  icon,
  title,
  children,
  action,
  role,
  className,
}: NoticeProps) {
  const warning = tone === 'warning';
  return (
    <div
      role={role}
      data-tone={tone}
      className={cn(
        'flex items-start gap-3 rounded-card px-4 py-3.5',
        warning
          ? 'bg-warning/10 shadow-[0_0_0_1px_hsl(var(--warning)/0.28)]'
          : 'bg-card shadow-[0_0_0_1px_hsl(var(--border))]',
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          'grid h-[30px] w-[30px] shrink-0 place-items-center rounded-full text-sm font-semibold',
          warning ? 'bg-warning/20 text-warning' : 'bg-foreground/[0.08] text-ink',
        )}
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        {title && <div className="mb-0.5 font-semibold text-ink">{title}</div>}
        {children && <div className="text-sm leading-[1.55] text-body">{children}</div>}
      </div>
      {action}
    </div>
  );
}

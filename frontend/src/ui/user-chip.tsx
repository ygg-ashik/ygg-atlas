// src/ui/user-chip.tsx
import type * as React from 'react';
import { Avatar } from './avatar';
import { cn } from './utils';

export interface UserChipProps {
  name: string;
  email: string;
  /** Usually a RolePill. */
  role?: React.ReactNode;
  /** A clay dot on the avatar (DESIGN.md › user-chip-dot), labelled for screen
   * readers: "3 pending approvals". None when absent. */
  dot?: string;
  className?: string;
}

/** The signed-in person at the sidebar foot (DESIGN.md › user-chip). */
export function UserChip({ name, email, role, dot, className }: UserChipProps) {
  return (
    <div className={cn('mt-auto flex items-center gap-2.5 rounded-[14px] p-2.5', className)}>
      <span className="relative shrink-0">
        <Avatar name={name || email} />
        {dot && (
          <span
            role="img"
            aria-label={dot}
            className="absolute -right-0.5 -top-0.5 h-[9px] w-[9px] rounded-full bg-primary shadow-[0_0_0_2px_hsl(var(--background))]"
          />
        )}
      </span>
      <div className="min-w-0">
        <div className="text-label font-medium leading-tight text-ink">{name}</div>
        <div className="max-w-[140px] truncate text-caption text-muted-foreground" title={email}>
          {email}
        </div>
      </div>
      {role && <span className="ml-auto">{role}</span>}
    </div>
  );
}

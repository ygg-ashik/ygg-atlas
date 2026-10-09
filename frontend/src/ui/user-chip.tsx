// src/ui/user-chip.tsx
import type * as React from 'react';
import { Avatar } from './avatar';
import { cn } from './utils';

export interface UserChipProps {
  name: string;
  email: string;
  /** Usually a RolePill. */
  role?: React.ReactNode;
  className?: string;
}

/** The signed-in person at the sidebar foot (DESIGN.md › user-chip). */
export function UserChip({ name, email, role, className }: UserChipProps) {
  return (
    <div className={cn('mt-auto flex items-center gap-2.5 rounded-[14px] p-2.5', className)}>
      <Avatar name={name} />
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

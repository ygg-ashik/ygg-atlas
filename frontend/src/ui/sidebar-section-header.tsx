// src/ui/sidebar-section-header.tsx
import type * as React from 'react';
import { cn } from './utils';

/** Uppercase micro-label above a sidebar nav group (DESIGN.md › sidebar-section-header).
 * Give it an id and point the group's aria-labelledby at it. */
export function SidebarSectionHeader({
  id,
  children,
  className,
}: {
  id?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <h2
      id={id}
      className={cn(
        'flex items-center gap-1.5 px-2.5 pb-[5px] pt-3.5 text-[11px] font-normal uppercase tracking-[0.06em] text-muted-foreground',
        className,
      )}
    >
      {children}
    </h2>
  );
}

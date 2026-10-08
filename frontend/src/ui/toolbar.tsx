// src/ui/toolbar.tsx
import * as React from 'react';
import { Glass } from './glass';
import { cn } from './utils';

interface ToolbarProps {
  title: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}

/** Floating glass page toolbar (DESIGN.md › glass-toolbar) plus the scroll-edge
 * blur beneath it. Place inside a `relative` page container; content below
 * reserves 84px (`pt-[84px]`) so nothing hides under the glass at rest. */
export function Toolbar({ title, children, className }: ToolbarProps) {
  return (
    <>
      <div
        aria-hidden
        className="scroll-edge-top pointer-events-none absolute inset-x-0 top-0 z-[5] h-20"
      />
      <Glass
        as="header"
        specular
        className={cn(
          'absolute inset-x-3.5 top-2.5 z-10 flex h-[52px] items-center gap-2 rounded-glass pl-[18px] pr-2',
          className,
        )}
      >
        <h1 className="min-w-0 flex-1 truncate font-serif text-section text-ink">{title}</h1>
        {children}
      </Glass>
    </>
  );
}

// src/ui/toolbar.tsx
import { Slot } from '@radix-ui/react-slot';
import * as React from 'react';
import { Glass } from './glass';
import { cn } from './utils';

interface ToolbarProps {
  title: React.ReactNode;
  /** Optional back link before the title: a `ToolbarCrumb` ("Users ›"). */
  crumb?: React.ReactNode;
  /** Muted mono route on the right (DESIGN.md › route-label); hidden below 1000px. */
  route?: string;
  children?: React.ReactNode;
  className?: string;
}

/** Floating glass page toolbar (DESIGN.md › glass-toolbar) plus the scroll-edge
 * blur beneath it. Place inside a `relative` page container; content below
 * reserves 84px (`pt-[84px]`) so nothing hides under the glass at rest. An ancestor may
 * set `--toolbar-lead` to make room for floating chrome at the left (the nav button). */
export function Toolbar({ title, crumb, route, children, className }: ToolbarProps) {
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
          'absolute inset-x-3.5 top-2.5 z-10 flex h-[52px] items-center gap-2 rounded-glass pl-[var(--toolbar-lead,18px)] pr-2',
          className,
        )}
      >
        {crumb}
        <h1 className="min-w-0 flex-1 truncate font-serif text-section text-ink">{title}</h1>
        {route && (
          <span
            data-route-label
            className="max-w-[46%] truncate whitespace-nowrap font-mono text-[11px] text-muted-foreground max-[999px]:hidden"
          >
            {route}
          </span>
        )}
        {children}
      </Glass>
    </>
  );
}

/** The toolbar's back link (DESIGN.md › toolbar-crumb): a muted serif link
 * followed by "›". Pass the router link as the only child; it receives the styles. */
export function ToolbarCrumb({ children }: { children: React.ReactElement }) {
  return (
    <nav aria-label="Breadcrumb" className="flex shrink-0 items-center gap-2 text-section">
      <Slot className="font-serif text-muted-foreground transition-colors hover:text-ink">
        {children}
      </Slot>
      <span aria-hidden className="text-muted-foreground">
        ›
      </span>
    </nav>
  );
}

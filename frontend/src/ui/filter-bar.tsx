// src/ui/filter-bar.tsx
import type * as React from 'react';
import { Search } from 'lucide-react';
import { Input } from './input';
import { cn } from './utils';

export interface FilterBarProps {
  /** Accessible name of the search landmark (e.g. "Filter users"). */
  label: string;
  search: {
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
    label: string;
  };
  /** Native selects or pills (e.g. Role, Status, Kind). */
  children?: React.ReactNode;
  /** Muted tabular count on the right ("12 users · 1 service"). */
  summary?: React.ReactNode;
  className?: string;
}

/** Search + filters under the page heading (DESIGN.md › filter-bar). Never on glass. */
export function FilterBar({ label, search, children, summary, className }: FilterBarProps) {
  return (
    <div
      role="search"
      aria-label={label}
      className={cn('mb-3 flex flex-wrap items-center gap-2', className)}
    >
      <div className="relative min-w-[220px] max-w-[360px] flex-1">
        <Search
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          type="search"
          aria-label={search.label}
          placeholder={search.placeholder}
          value={search.value}
          onChange={(e) => search.onChange(e.target.value)}
          className="pl-[34px]"
        />
      </div>
      {children}
      {summary && (
        <span className="ml-auto text-caption tabular-nums text-muted-foreground">{summary}</span>
      )}
    </div>
  );
}

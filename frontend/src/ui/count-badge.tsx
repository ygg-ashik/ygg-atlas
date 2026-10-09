// src/ui/count-badge.tsx
import { cn } from './utils';

export interface CountBadgeProps {
  count: number;
  /** What is counted, for screen readers: "pending requests". */
  label: string;
  className?: string;
}

/** Clay pill with a tabular count on a nav item (DESIGN.md › count-badge).
 * Renders nothing at zero; caps the visible number at 99+. */
export function CountBadge({ count, label, className }: CountBadgeProps) {
  if (count <= 0) return null;
  return (
    <span
      className={cn(
        'ml-auto inline-grid h-5 min-w-5 place-items-center rounded-full bg-primary px-1.5 text-[11px] font-semibold tabular-nums text-primary-foreground',
        className,
      )}
    >
      <span aria-hidden>{count > 99 ? '99+' : count}</span>
      <span className="sr-only">
        {count} {label}
      </span>
    </span>
  );
}

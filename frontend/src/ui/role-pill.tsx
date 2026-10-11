// src/ui/role-pill.tsx
import { cn } from './utils';

/** A user's role as a hairline pill with the clay diamond (DESIGN.md › role-pill). */
export function RolePill({ role, className }: { role: string; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-border bg-card-2 px-2.5 py-0.5 text-xs font-medium text-ink',
        className,
      )}
    >
      <b aria-hidden className="inline-block h-1.5 w-1.5 rotate-45 rounded-[2px] bg-primary" />
      {role}
    </span>
  );
}

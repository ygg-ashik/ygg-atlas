// src/ui/select.tsx
import * as React from 'react';
import { ChevronDown } from 'lucide-react';
import { FIELD_CLASS } from './field-styles';
import { cn } from './utils';

/** Native select styled as a field, with a chevron (DESIGN.md › Form fields).
 * Native keeps keyboard, screen-reader and mobile pickers correct for free. */
const Select = React.forwardRef<HTMLSelectElement, React.ComponentProps<'select'>>(
  ({ className, children, ...props }, ref) => (
    <span className="relative inline-flex">
      <select
        ref={ref}
        className={cn(FIELD_CLASS, 'w-auto cursor-pointer appearance-none pr-8', className)}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        aria-hidden
        className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
      />
    </span>
  ),
);
Select.displayName = 'Select';

export { Select };

// src/ui/checkbox.tsx
import * as React from 'react';
import { cn } from './utils';

export interface CheckboxProps extends Omit<React.ComponentProps<'input'>, 'type'> {
  label: React.ReactNode;
}

/** Native checkbox with its label, for explicit confirmations
 * ("I understand this restricts 4 members"). */
const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ label, className, ...props }, ref) => (
    <label
      className={cn(
        'inline-flex cursor-pointer items-center gap-2 text-[13.5px] text-body has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-55',
        className,
      )}
    >
      <input
        ref={ref}
        type="checkbox"
        className="h-4 w-4 shrink-0 cursor-[inherit] accent-primary focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/15"
        {...props}
      />
      {label}
    </label>
  ),
);
Checkbox.displayName = 'Checkbox';

export { Checkbox };

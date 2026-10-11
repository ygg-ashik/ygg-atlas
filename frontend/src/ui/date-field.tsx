// src/ui/date-field.tsx
import * as React from 'react';
import { FIELD_CLASS, FIELD_MONO_CLASS } from './field-styles';
import { cn } from './utils';

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** True for a real calendar date written as YYYY-MM-DD (UTC). */
export function isIsoDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export interface DateFieldProps extends Omit<React.ComponentProps<'input'>, 'type' | 'value'> {
  value: string;
}

/** Flag a value only once it can be judged: complete (10 chars) or left (blurred). */
export function isDateFlagged(value: string, left: boolean): boolean {
  const judged = left || value.length >= 10;
  return judged && value !== '' && !isIsoDate(value);
}

/** ISO date as a mono text field (DESIGN.md › field-date). Empty is allowed
 * (e.g. "Never"); anything else must be a real YYYY-MM-DD date. Never flagged
 * mid-typing: only when complete or on blur. */
const DateField = React.forwardRef<HTMLInputElement, DateFieldProps>(
  ({ value, className, onBlur, onFocus, ...props }, ref) => {
    const [left, setLeft] = React.useState(false);
    const invalid = isDateFlagged(value, left);
    return (
      <input
        ref={ref}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        spellCheck={false}
        placeholder="YYYY-MM-DD"
        value={value}
        aria-invalid={invalid || undefined}
        className={cn(FIELD_CLASS, FIELD_MONO_CLASS, 'w-[150px]', className)}
        {...props}
        onFocus={(e) => {
          setLeft(false);
          onFocus?.(e);
        }}
        onBlur={(e) => {
          setLeft(true);
          onBlur?.(e);
        }}
      />
    );
  },
);
DateField.displayName = 'DateField';

export { DateField };

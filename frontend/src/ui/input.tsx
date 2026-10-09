import * as React from 'react';
import { FIELD_CLASS, FIELD_MONO_CLASS } from './field-styles';
import { cn } from './utils';

export interface InputProps extends React.ComponentProps<'input'> {
  /** Mono for resource paths, ids and tokens (DESIGN.md › field-input-mono). */
  mono?: boolean;
  /** Marks the field invalid (negative border); pair with a FieldError. */
  invalid?: boolean;
}

/** Text input on a solid surface (DESIGN.md › field-input). */
const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = 'text', mono = false, invalid, ...props }, ref) => (
    <input
      type={type}
      aria-invalid={invalid || undefined}
      className={cn(FIELD_CLASS, mono && FIELD_MONO_CLASS, className)}
      ref={ref}
      {...props}
    />
  ),
);
Input.displayName = 'Input';

export { Input };
